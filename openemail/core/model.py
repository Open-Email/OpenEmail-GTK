# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from base64 import b64decode
from contextlib import suppress
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime
from hashlib import sha256
from itertools import chain
from types import NoneType, UnionType
from typing import Any, NamedTuple, Protocol, Self, get_args, get_origin

from . import crypto
from .crypto import Key, KeyPair

MAX_HEADERS_SIZE = 512_000
MESSAGE_LIFETIME = 7


class Address:
    """A Mail/HTTPS address."""

    local_part: str
    host_part: str

    def __init__(self, address: str) -> None:
        if not re.match(
            r"^[a-z0-9][a-z0-9\.\-_\+]{2,}@[a-z0-9.-]+\.[a-z]{2,}|xn--[a-z0-9]{2,}$",
            address := address.lower(),
        ):
            msg = f'Email address "{address}" is invalid'
            raise ValueError(msg)

        try:
            self.local_part, self.host_part = address.split("@")
        except ValueError as error:
            msg = f'Email address "{address}" contains more than a single @ character'
            raise ValueError(msg) from error

    def __repr__(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return f"{self.local_part}@{self.host_part}"

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    def __ne__(self, other: object) -> bool:
        return str(self) != str(other)

    def __lt__(self, other: object) -> bool:
        return str(self) < str(other)

    def __gt__(self, other: object) -> bool:
        return str(self) > str(other)

    def __le__(self, other: object) -> bool:
        return str(self) >= str(other)

    def __ge__(self, other: object) -> bool:
        return str(self) <= str(other)

    def __hash__(self) -> int:
        return hash(str(self))


def generate_link(first: Address, second: Address) -> str:
    """Generate a connection identifier for `address_1` and `address_2`."""
    return sha256(
        f"{min(first, second)}{max(first, second)}".encode("ascii")
    ).hexdigest()


def generate_ident(author: Address) -> str:
    """Generate a unique ID for a new message."""
    return sha256(
        "".join(
            (
                crypto.random_string(length=24),
                author.host_part,
                author.local_part,
            )
        ).encode("utf-8")
    ).hexdigest()


@dataclass(slots=True)
class User:
    """A local user."""

    address: Address

    encryption_keys: KeyPair
    signing_keys: KeyPair

    @property
    def logged_in(self) -> bool:
        """Whether the user has valid credentials."""
        return all(hasattr(self, f.name) for f in fields(User))

    def __init__(self) -> None: ...


class AttachmentProperties(NamedTuple):
    """A file attached to a message."""

    name: str
    ident: str
    type: str = "application/octet-stream"
    size: int = 0
    part: tuple[int, int] = (0, 0)
    modified: str | None = None

    @property
    def dict(self) -> dict[str, str]:
        """A dictionary representation of `self`."""
        return (
            {"name": self.name, "id": self.ident, "type": self.type}
            | ({"size": str(self.size)} if self.size else {})
            | ({"part": "/".join(map(str, self.part))} if all(self.part) else {})
            | ({"modified": self.modified} if self.modified else {})
        )

    @staticmethod
    def parse_part(part: str) -> tuple[int, int]:
        """Parse `part` to be used for `AttachmentProperties`.

        This method never fails, it returns `(0, 0)` if the value cannot be parsed.
        """
        split = tuple(int(p.strip()) for p in part.split("/"))

        try:
            return (split[0], split[1])
        except (IndexError, ValueError):
            return (0, 0)


class Message(Protocol):
    """A Mail/HTTPS message."""

    ident: str
    author: Address
    original_author: Address
    date: datetime
    subject: str

    readers: list[Address]
    access_key: bytes | None

    attachments: dict[str, list["Message"]]
    children: list["Message"]
    file: AttachmentProperties | None
    attachment_url: str | None

    body: str | None
    new: bool  # TODO

    @property
    def is_broadcast(self) -> bool:
        """Whether `self` is a broadcast."""
        raise NotImplementedError


@dataclass(slots=True)
class IncomingMessage:
    """A remote message."""

    ident: str
    author: Address
    original_author: Address = field(init=False)
    date: datetime = field(init=False)
    checksum: str | None = field(init=False, default=None)
    subject: str = field(init=False)
    subject_id: str | None = field(init=False, default=None)
    headers: dict[str, str]

    readers: list[Address] = field(init=False, default_factory=list)
    access_links: str | None = field(init=False, default=None)
    access_key: bytes | None = field(init=False, default=None)
    private_key: Key

    files: dict[str, AttachmentProperties] = field(init=False, default_factory=dict)
    attachments: dict[str, list[Self]] = field(init=False, default_factory=dict)
    children: list[Self] = field(init=False, default_factory=list)
    file: AttachmentProperties | None = field(init=False, default=None)
    attachment_url: str | None = None
    parent_id: str | None = field(init=False, default=None)

    body: str | None = None
    new: bool = False

    @property
    def is_broadcast(self) -> bool:
        """Whether `self` is a broadcast."""
        return not self.access_links

    @property
    def is_child(self) -> bool:
        """Whether `self` is a child."""
        return bool(self.parent_id)

    def __post_init__(self) -> None:
        message_headers: str | None = None

        self.headers = {k.lower(): v.strip() for k, v in self.headers.items()}

        for key, value in self.headers.items():
            match key:
                case "message-access":
                    self.access_links = value
                    reader_links = (
                        link.strip() for link in self.access_links.split(",")
                    )

                    for link in reader_links:
                        try:
                            reader = parse_headers(link)
                            self.access_key = crypto.decrypt_anonymous(
                                reader["value"], self.private_key
                            )
                            break

                        except (KeyError, ValueError):
                            continue

                case "message-headers":
                    message_headers = value

                case "message-checksum":
                    self.checksum = value

        if not message_headers:
            msg = "Empty message headers"
            raise ValueError(msg)

        if not self.checksum:
            msg = "Missing checksum"
            raise ValueError(msg)

        checksum = parse_headers(self.checksum)

        try:
            if checksum["algorithm"] != crypto.CHECKSUM_ALGORITHM:
                msg = "Unsupported checksum algorithm"
                raise ValueError(msg)

            if (
                checksum["value"]
                != sha256(
                    (
                        "".join(
                            (
                                self.headers.get(field.lower(), "")
                                for field in (
                                    header.strip()
                                    for header in checksum["order"].split(":")
                                )
                            )
                        )
                    ).encode("utf-8")
                ).hexdigest()
            ):
                msg = "Invalid checksum"
                raise ValueError(msg)

        except KeyError as error:
            msg = "Bad checksum format"
            raise ValueError(msg) from error

        try:
            header_bytes = b64decode(parse_headers(message_headers)["value"])

            if (not self.is_broadcast) and self.access_key:
                header_bytes = crypto.decrypt_xchacha20poly1305(
                    header_bytes, self.access_key
                )

            try:
                headers = {
                    (split := header.split(":", 1))[0].lower(): split[1].strip()
                    for header in header_bytes.decode("utf-8").split("\n")
                }
            except UnicodeDecodeError as error:
                msg = "Unable to decode headers"
                raise ValueError(msg) from error

        except (IndexError, KeyError, ValueError) as error:
            msg = "Could not parse headers"
            raise ValueError(msg) from error

        if sum(len(k) + len(v) for k, v in headers.items()) > MAX_HEADERS_SIZE:
            msg = "Envelope size exceeds MAX_HEADERS_SIZE"
            raise ValueError(msg)

        try:
            self.ident = headers["id"]
            self.date = datetime.fromisoformat(headers["date"])
            self.subject = headers["subject"]
            self.original_author = Address(headers["author"])
        except KeyError as error:
            msg = "Incomplete header contents"
            raise ValueError(msg) from error

        self.subject_id = headers.get("subject.id", self.ident)
        self.parent_id = headers.get("parent-id")

        def str_to_int(string: str | None) -> int:
            return int(string) if string and string.isdigit() else 0

        if files := headers.get("files"):
            for file in files.split(","):
                file_headers = parse_headers(file.strip())
                try:
                    self.files[file_headers["id"]] = AttachmentProperties(
                        file_headers["name"],
                        file_headers["id"],
                        file_headers.get("type") or "application/octet-stream",
                        str_to_int(file_headers.get("size")),
                        AttachmentProperties.parse_part(part)
                        if (part := file_headers.get("part"))
                        else (0, 0),
                        file_headers.get("modified"),
                    )
                except KeyError:
                    continue

        elif (file := headers.get("file")) and (file_headers := parse_headers(file)):
            with suppress(KeyError):
                self.file = AttachmentProperties(
                    file_headers["name"],
                    self.ident,
                    file_headers.get("type") or "application/octet-stream",
                    str_to_int(file_headers.get("size"))
                    or str_to_int(self.headers.get("size")),
                    AttachmentProperties.parse_part(part)
                    if (part := file_headers.get("part"))
                    else (0, 0),
                    file_headers.get("modified"),
                )

        if readers := headers.get("readers"):
            for reader in readers.split(","):
                try:
                    self.readers.append(Address(reader.strip()))
                except ValueError:  # noqa: PERF203
                    continue

    def add_child(self, child: Self) -> None:
        """Add `child` to `self.children`, updating its properties accordingly."""
        self.children.append(child)

        if not (
            self.files
            and (child.parent_id == self.ident)
            and (props := self.files.get(child.ident))
        ):
            return

        child.file = props

    def reconstruct_from_children(self) -> None:
        """Reconstruct the entire contents of this message from all of its children.

        Should only be called after all children have been fetched and added.
        """
        parts: list[Self] = []

        for child in self.children:
            if not (child.parent_id and (child.parent_id == self.ident)):
                continue

            if child.ident not in self.files:
                parts.append(child)

            if not child.file:
                continue

            if not (attachment := self.attachments.get(child.file.name)):
                attachment = self.attachments[child.file.name] = []

            attachment.append(child)

        for part in chain((parts,), self.attachments.values()):
            part.sort(key=lambda p: p.file.part[0] if p.file else 0)

        for part in parts:
            self.body = (self.body or "") + (part.body or "")


@dataclass(slots=True)
class Notification:
    """A Mail/HTTPS notification."""

    ident: str
    received_on: datetime
    link: str
    notifier: Address
    fp: str

    @property
    def is_expired(self) -> bool:
        """Whether the notification has already expired."""
        return (self.received_on - datetime.now(UTC)).days >= MESSAGE_LIFETIME


def parse_headers(data: str) -> dict[str, str]:
    """Parse `data` into a dictionary of headers."""
    try:
        return {
            (split := attr.strip().split("=", 1))[0].lower(): split[1]
            for attr in data.split(";")
        }
    except (IndexError, ValueError):
        return {}


@dataclass(slots=True)
class Profile:
    """A user's profile."""

    address: Address

    name: str
    signing_key: Key
    updated: datetime

    about: str | None
    address_expansion: str | None
    away_warning: str | None
    birthday: date | None
    books: str | None
    department: str | None
    education: str | None
    encryption_key: Key | None
    gender: str | None
    interests: str | None
    job_title: str | None
    languages: str | None
    last_signing_key: Key | None
    location: str | None
    mailing_address: str | None
    movies: str | None
    music: str | None
    notes: str | None
    organization: str | None
    phone: str | None
    places_lived: str | None
    relationship_status: str | None
    sports: str | None
    streams: str | None
    status: str | None
    website: str | None
    work: str | None

    away: bool = False
    last_seen_public: bool = True
    public_links: bool = True
    public_access: bool = True

    def __init__(self, address: Address, data: str) -> None:
        parsed_fields = {
            (split := field.split(":", 1))[0].strip().lower(): split[1].strip()
            for field in (line.strip() for line in data.split("\n") if ":" in line)
            if not field.startswith("#")
        }

        for f in fields(Profile):
            if f.name == "address":
                continue

            value = parsed_fields.get(f.name.replace("_", "-"))
            required = get_origin(t := f.type) is not UnionType

            if value is None:
                if isinstance(t, type) and isinstance(f.default, t):
                    setattr(self, f.name, f.default)
                    continue

                if required:
                    msg = f'Required field "{f.name}" does not exist'
                    raise ValueError(msg)

                setattr(self, f.name, None)
                continue

            if not required:
                t = next(iter(set(get_args(f.type)) - {NoneType}))

            if t is bool:
                value = value == "Yes"

            elif t is date:
                try:
                    value = date.fromisoformat(value)
                except ValueError:
                    value = None

            elif t is datetime:
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    value = None

            elif t is Key:
                attrs = parse_headers(value)

                try:
                    value = Key(
                        b64decode(attrs["value"]),
                        attrs["algorithm"],
                        attrs.get("id"),
                    )
                except (KeyError, ValueError):
                    value = None

            if required and (value is None):
                msg = f'Required field "{f.name}" contains invalid data'
                raise ValueError(msg)

            setattr(self, f.name, value)

        self.address = address


def to_fields(dictionary: dict[Any, Any]) -> str:
    r"""Serialize `dictionary` into a string in `k1: v\nk2: v` format."""
    return "\n".join(f"{k}: {v}" for k, v in dictionary.items())


def to_attrs(dictionary: dict[Any, Any]) -> str:
    """Serialize `dictionary` into a string in `k1=v; k2=v` format."""
    return "; ".join(f"{k}={v}" for k, v in dictionary.items())
