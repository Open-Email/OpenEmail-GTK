# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import re
from base64 import b64decode
from contextlib import suppress
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from hashlib import sha256
from itertools import chain
from logging import getLogger
from types import NoneType, UnionType
from typing import Any, NamedTuple, Protocol, Self, get_args, get_origin

from . import crypto
from .crypto import Key, KeyPair

MAX_HEADERS_SIZE = 512_000
MAX_MESSAGE_SIZE = 64_000_000
MESSAGE_LIFETIME = 7

logger = getLogger(__name__)


class WriteError(Exception):
    """Raised if writing to the server fails."""


class Address(str):
    """A Mail/HTTPS address."""

    __slots__ = ("host_part", "local_part")

    def __new__(cls, address: str) -> Self:
        """Validate `address`."""
        if not re.match(
            r"^[a-z0-9][a-z0-9\.\-_\+]{2,}@[a-z0-9.-]+\.[a-z]{2,}|xn--[a-z0-9]{2,}$",
            address := address.lower(),
        ):
            e = f'Email address "{address}" is invalid'
            raise ValueError(e)

        return super().__new__(cls, address)

    def __init__(self, address: str):
        self.local_part, self.host_part = address.split("@")


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

    def __init__(self): ...


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

    attachments: dict[str, list[Self]]
    children: list[Self]
    file: AttachmentProperties | None
    attachment_url: str | None

    body: str | None
    new: bool  # TODO

    @property
    def is_broadcast(self) -> bool:
        """Whether `self` is a broadcast."""
        raise NotImplementedError


class DraftMessage:
    """A local message, saved as a draft."""

    @property
    def is_broadcast(self) -> bool:
        """Whether `self` is a broadcast."""
        return self._broadcast

    def __init__(
        self,
        ident: str | None = None,
        date: datetime | None = None,
        subject: str = "",
        subject_id: str | None = None,
        readers: list[Address] | None = None,
        body: str | None = None,
        broadcast: bool = False,
    ):
        from .client import user

        self.ident = ident or generate_id(user.address)
        self.author = self.original_author = user.address
        self.date = date or datetime.now(UTC)
        self.subject = subject
        self.subject_id = subject_id

        self.readers = readers or []
        self.access_key: bytes | None = None

        self.attachments = dict[str, list[DraftMessage]]()
        self.children = list[DraftMessage]()
        self.file: AttachmentProperties | None = None
        self.attachment_url: str | None = None

        self.body = body
        self.new: bool = False

        self._broadcast = broadcast


class OutgoingMessage:
    """A local message, to be sent."""

    @property
    def is_broadcast(self) -> bool:
        """Whether `self` is a broadcast."""
        return not self.readers

    def __init__(
        self,
        date: datetime | None = None,
        subject: str = "",
        subject_id: str | None = None,
        readers: list[Address] | None = None,
        files: dict[AttachmentProperties, bytes] | None = None,
        file: AttachmentProperties | None = None,
        attachment_url: str | None = None,
        parent_id: str | None = None,
        body: str | None = None,
        content: bytes = b"",
    ):
        from .client import user

        self.ident = generate_id(user.address)
        self.author = self.original_author = user.address
        self.date = date or datetime.now(UTC)
        self.subject = subject
        self.subject_id = subject_id or self.ident
        self.headers = dict[str, str]()

        self.readers = readers or []
        self.access_key: bytes | None = None

        self.files = files or {}
        self.attachments = dict[str, list[OutgoingMessage]]()
        self.children = list[OutgoingMessage]()
        self.file = file
        self.attachment_url = attachment_url
        self.parent_id = parent_id

        self.body = body
        self.content = content
        self.new: bool = False
        self.sending: bool = False

        for props, data in self.files.items():
            self.attachments[props.name] = []
            for index, start in enumerate(range(0, len(data), MAX_MESSAGE_SIZE)):
                self.attachments[props.name].append(
                    OutgoingMessage(
                        self.date,
                        self.subject,
                        self.subject_id,
                        self.readers,
                        file=AttachmentProperties(
                            name=props.name,
                            ident=props.ident,
                            type=props.type,
                            size=len(data),
                            part=(index + 1, len(self.files)),
                            modified=props.modified
                            or self.date.isoformat(timespec="seconds"),
                        ),
                        parent_id=self.ident,
                        content=data[start : start + MAX_MESSAGE_SIZE],
                    )
                )

        if not self.body:
            return

        self.content = self.body.encode("utf-8")


class IncomingMessage:
    """A remote message."""

    @property
    def is_broadcast(self) -> bool:
        """Whether `self` is a broadcast."""
        return not self.access_links

    @property
    def is_child(self) -> bool:
        """Whether `self` is a child."""
        return bool(self.parent_id)

    def __init__(
        self,
        ident: str,
        author: Address,
        headers: dict[str, str],
        private_key: Key,
        new: bool = False,
    ):
        self.ident = ident
        self.author = author
        self.original_author: Address
        self.date: datetime
        self.checksum: str | None = None
        self.subject: str
        self.subject_id: str | None = None
        self.headers = {k.lower(): v.strip() for k, v in headers.items()}

        self.readers = list[Address]()
        self.access_links: str | None = None
        self.access_key: bytes | None = None
        self.private_key = private_key

        self.files = dict[str, AttachmentProperties]()
        self.attachments = dict[str, list[IncomingMessage]]()
        self.children = list[IncomingMessage]()
        self.file: AttachmentProperties | None = None
        self.attachment_url: str | None = None
        self.parent_id: str | None = None

        self.body: str | None = None
        self.new = new

        message_headers: str | None = None
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
            e = "Empty message headers"
            raise ValueError(e)

        if not self.checksum:
            e = "Missing checksum"
            raise ValueError(e)

        checksum = parse_headers(self.checksum)

        try:
            if checksum["algorithm"] != crypto.CHECKSUM_ALGORITHM:
                e = "Unsupported checksum algorithm"
                raise ValueError(e)

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
                e = "Invalid checksum"
                raise ValueError(e)

        except KeyError as error:
            e = "Bad checksum format"
            raise ValueError(e) from error

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
                e = "Unable to decode headers"
                raise ValueError(e) from error

        except (IndexError, KeyError, ValueError) as error:
            e = "Could not parse headers"
            raise ValueError(e) from error

        if sum(len(k) + len(v) for k, v in headers.items()) > MAX_HEADERS_SIZE:
            e = "Envelope size exceeds MAX_HEADERS_SIZE"
            raise ValueError(e)

        try:
            self.ident = headers["id"]
            self.date = datetime.fromisoformat(headers["date"])
            self.subject = headers["subject"]
            self.original_author = Address(headers["author"])
        except KeyError as error:
            e = "Incomplete header contents"
            raise ValueError(e) from error

        self.subject_id = headers.get("subject-id", self.ident)
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

    def add_child(self, child: Self):
        """Add `child` to `self.children`, updating its properties accordingly."""
        self.children.append(child)

        if not (
            self.files
            and (child.parent_id == self.ident)
            and (props := self.files.get(child.ident))
        ):
            return

        child.file = props

    def reconstruct_from_children(self):
        """Reconstruct the entire contents of this message from all of its children.

        Should only be called after all children have been fetched and added.
        """
        parts = list[IncomingMessage]()

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


class Notification(NamedTuple):
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

    def __init__(self, address: Address, data: str):
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
                    e = f'Required field "{f.name}" does not exist'
                    raise ValueError(e)

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
                e = f'Required field "{f.name}" contains invalid data'
                raise ValueError(e)

            setattr(self, f.name, value)

        self.address = address


def parse_headers(data: str) -> dict[str, str]:
    """Parse `data` into a dictionary of headers."""
    try:
        return {
            (split := attr.strip().split("=", 1))[0].lower(): split[1]
            for attr in data.split(";")
        }
    except (IndexError, ValueError):
        return {}


def generate_link(first: Address, second: Address) -> str:
    """Generate a connection identifier for `address_1` and `address_2`."""
    return sha256(
        f"{min(first, second)}{max(first, second)}".encode("ascii")
    ).hexdigest()


def generate_id(author: Address) -> str:
    """Generate a unique ID for a new message."""
    return sha256(
        "".join((
            crypto.random_string(length=24),
            author.host_part,
            author.local_part,
        )).encode("utf-8")
    ).hexdigest()


def to_fields(dictionary: dict[Any, Any]) -> str:
    r"""Serialize `dictionary` into a string in `k1: v\nk2: v` format."""
    return "\n".join(f"{k}: {v}" for k, v in dictionary.items())


def to_attrs(dictionary: dict[Any, Any]) -> str:
    """Serialize `dictionary` into a string in `k1=v; k2=v` format."""
    return "; ".join(f"{k}={v}" for k, v in dictionary.items())
