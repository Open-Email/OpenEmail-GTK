# model.py
#
# Authors: kramo
# Copyright 2025 Mercata Sagl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from abc import ABC, abstractmethod
from base64 import b64decode
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timezone
from hashlib import sha256
from re import match
from typing import Generic, NamedTuple, Self, TypeVar

from gi.repository.GLib import base64_decode

from .crypto import (
    CHECKSUM_ALGORITHM,
    Key,
    decrypt_anonymous,
    decrypt_xchacha20poly1305,
)

T = TypeVar("T")


class Address:
    """A Mail/HTTPS address."""

    local_part: str
    host_part: str

    def __init__(self, address: str) -> None:
        if not match(
            r"^[a-z0-9][a-z0-9\.\-_\+]{2,}@[a-z0-9.-]+\.[a-z]{2,}|xn--[a-z0-9]{2,}$",
            address := address.lower(),
        ):
            raise ValueError(f'Email address "{address}" is invalid')

        try:
            self.local_part, self.host_part = address.split("@")
        except ValueError as error:
            raise ValueError(
                f'Email address "{address}" contains more than a single @ character'
            ) from error

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


@dataclass(slots=True)
class User:
    """A local user."""

    address: Address

    public_encryption_key: Key
    private_encryption_key: Key

    public_signing_key: Key
    private_signing_key: Key

    @property
    def logged_in(self) -> bool:
        """Whether or not the user has valid credentials."""
        for f in fields(User):
            if not hasattr(self, f.name):
                return False

        return True

    def __init__(self) -> None: ...


class AttachmentProperties(NamedTuple):
    """A file attached to a message."""

    name: str
    part: str | None


@dataclass(slots=True)
class Envelope:
    """Metadata about a message."""

    message_id: str
    headers: dict[str, str]
    author: Address
    user: User | None = None

    date: datetime = field(init=False)
    subject: str = field(init=False)
    original_author: Address = field(init=False)
    readers: list[Address] = field(init=False, default_factory=list)

    checksum: str | None = field(init=False, default=None)

    access_links: str | None = field(init=False, default=None)
    access_key: bytes | None = field(init=False, default=None)

    parent_id: str | None = field(init=False, default=None)
    part: int = field(init=False, default=0)
    file_name: str | None = field(init=False, default=None)
    files: dict[str, AttachmentProperties] = field(init=False, default_factory=dict)

    subject_id: str | None = field(init=False, default=None)

    @property
    def is_broadcast(self) -> bool:
        """Whether or not the message is a broadcast."""
        return not bool(self.access_links)

    @property
    def is_child(self) -> bool:
        """Whether or not the message is a child."""
        return bool(self.parent_id)

    def __post_init__(self) -> None:
        message_headers: str | None = None

        self.headers = {
            key.lower(): value.strip() for key, value in self.headers.items()
        }

        for key, value in self.headers.items():
            match key:
                case "message-access":
                    self.access_links = value
                    reader_links = (
                        link.strip() for link in self.access_links.split(",")
                    )

                    if not self.user:
                        break

                    for link in reader_links:
                        try:
                            reader = parse_headers(link)
                            self.access_key = decrypt_anonymous(
                                reader["value"],
                                self.user.private_encryption_key,
                                self.user.public_encryption_key,
                            )
                            break

                        except (KeyError, ValueError):
                            continue

                case "message-headers":
                    message_headers = value

                case "message-checksum":
                    self.checksum = value

        if not message_headers:
            raise ValueError("Empty message headers")

        if not self.checksum:
            raise ValueError("Missing checksum")

        sum = parse_headers(self.checksum)

        try:
            if sum["algorithm"] != CHECKSUM_ALGORITHM:
                raise ValueError("Unsupported checksum algorithm")

            if (
                sum["value"]
                != sha256(
                    (
                        "".join(
                            tuple(
                                self.headers.get(field.lower(), "")
                                for field in (
                                    header.strip() for header in sum["order"].split(":")
                                )
                            )
                        )
                    ).encode("utf-8")
                ).hexdigest()
            ):
                raise ValueError("Invalid checksum")

        except KeyError as error:
            raise ValueError("Bad checksum format") from error

        try:
            header_bytes = b64decode(parse_headers(message_headers)["value"])

            if (not self.is_broadcast) and self.access_key:
                header_bytes = decrypt_xchacha20poly1305(header_bytes, self.access_key)

            try:
                headers = {
                    (split := header.split(":", 1))[0].lower(): split[1].strip()
                    for header in header_bytes.decode("utf-8").split("\n")
                }
            except UnicodeDecodeError as error:
                raise ValueError("Unable to decode headers") from error

        except (IndexError, KeyError, ValueError) as error:
            raise ValueError("Could not parse headers") from error

        try:
            self.message_id = headers["id"]
            self.date = datetime.fromisoformat(headers["date"])
            self.subject = headers["subject"]
            self.original_author = Address(headers["author"])
        except KeyError as error:
            raise ValueError("Incomplete header contents") from error

        self.subject_id = headers.get("subject.id", self.message_id)
        self.parent_id = headers.get("parent-id")

        if files := headers.get("files"):
            for file in files.split(","):
                file_headers = parse_headers(file.strip())
                try:
                    self.files[file_headers["id"]] = AttachmentProperties(
                        file_headers["name"],
                        file_headers.get("part"),
                    )
                except KeyError:
                    continue

        elif (file := headers.get("file")) and (file_headers := parse_headers(file)):
            # The macOS client does not seem to implement this header and relies only on Files
            self.file_name = file_headers.get("name")

            if part := file_headers.get("part"):
                try:
                    self.part = int(part.split("/")[0].strip())
                except ValueError:
                    pass

        if readers := headers.get("readers"):
            for reader in readers.split(","):
                try:
                    self.readers.append(Address(reader.strip()))
                except ValueError:
                    continue


@dataclass(slots=True)
class Message:
    """An envelope and its contents."""

    envelope: Envelope
    body: str | None = None
    attachment_url: str | None = None

    children: list[Self] = field(init=False, default_factory=list)
    attachments: dict[str, list[Self]] = field(init=False, default_factory=dict)

    def add_child(self, child: Self) -> None:
        """Add `child` to `self.children`, updating its properties accordingly."""
        self.children.append(child)

        if not (
            self.envelope.files
            and (child.envelope.parent_id == self.envelope.message_id)
            and (props := self.envelope.files.get(child.envelope.message_id))
        ):
            return

        child.envelope.file_name = props.name
        if props.part:
            try:
                child.envelope.part = int(props.part.split("/")[0].strip())
            except ValueError:
                pass

    def reconstruct_from_children(self) -> None:
        """Reconstruct the entire content of this message from all of its children.

        Should only be called after all children have been fetched and added.
        """
        parts: list[Self] = []

        for child in self.children:
            if not (
                child.envelope.parent_id
                and (child.envelope.parent_id == self.envelope.message_id)
            ):
                continue

            if child.envelope.message_id not in self.envelope.files:
                parts.append(child)

            if not child.envelope.file_name:
                continue

            if not (attachment := self.attachments.get(child.envelope.file_name)):
                attachment = self.attachments[child.envelope.file_name] = []

            attachment.append(child)

        parts.sort(key=lambda part: part.envelope.part)
        for part in parts:
            self.body = f"{self.body or ''}{part.body or ''}"

        for name, attachment in self.attachments.items():
            attachment.sort(key=lambda part: part.envelope.part)


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
        """Whether or not the notification has already expired."""
        return (self.received_on - datetime.now(timezone.utc)).days >= 7


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
class ProfileField(ABC, Generic[T]):
    """A generic profile field."""

    default_value: T | None = None

    @property
    def value(self) -> T:
        """The value of the field."""
        if self.default_value is None:
            raise ValueError("Profile incorrectly initialized")

        return self.default_value

    @abstractmethod
    def update_value(self, data: str | None) -> None:
        """Update `self.value` from `data`."""


class StringField(ProfileField[str]):
    """A profile field representing a string."""

    def __str__(self) -> str:
        return self.value

    def update_value(self, data: str | None) -> None:
        """Update `self.value` to `data`."""
        self.default_value = data


class BoolField(ProfileField[bool]):
    """A profile field representing a boolean."""

    def __str__(self) -> str:
        return "Yes" if self.value else "No"

    def update_value(self, data: str | None) -> None:
        """Update `self.value` from `data`."""
        if data is not None:
            self.default_value = data == "Yes"


class DateField(ProfileField[date]):
    """A profile field representing a date."""

    def __str__(self) -> str:
        return self.value.strftime("%x")

    def update_value(self, data: str | None) -> None:
        """Update `self.value` from `data`."""
        if not data:
            return

        try:
            self.default_value = date.fromisoformat(data)
        except ValueError:
            pass


class DateTimeField(ProfileField[datetime]):
    """A profile field representing a date and time."""

    def __str__(self) -> str:
        return self.value.strftime("%c")

    def update_value(self, data: str | None) -> None:
        """Update `self.value` from `data`."""
        if not data:
            return

        try:
            self.default_value = datetime.fromisoformat(data)
        except ValueError:
            pass


class KeyField(ProfileField[Key]):
    """A profile field representing a key."""

    def __str__(self) -> str:
        return str(self.value)

    def update_value(self, data: str | None) -> None:
        """Update `self.value` from `data`."""
        if not data:
            return

        attrs = parse_headers(data)

        try:
            self.default_value = Key(
                base64_decode(attrs["value"]),
                attrs["algorithm"],
                attrs.get("id"),
            )
        except (KeyError, ValueError):
            pass


class Profile:
    """A user's profile."""

    address: Address

    required: dict[str, ProfileField]
    optional: dict[str, ProfileField | None]

    def __init__(self, address: Address, data: str) -> None:
        self.address = address

        self.required = {
            "name": StringField(),
            "signing-key": KeyField(),
            "updated": DateTimeField(),
        }

        self.optional = {
            "about": StringField(),
            "away": BoolField(False),
            "away-warning": StringField(),
            "birthday": DateField(),
            "books": StringField(),
            "department": StringField(),
            "education": StringField(),
            "encryption-key": KeyField(),
            "gender": StringField(),
            "interests": StringField(),
            "job-title": StringField(),
            "languages": StringField(),
            "last-seen-public": BoolField(True),
            "last-signing-key": KeyField(),
            "location": StringField(),
            "mailing-address": StringField(),
            "movies": StringField(),
            "music": StringField(),
            "notes": StringField(),
            "organization": StringField(),
            "phone": StringField(),
            "place-slived": StringField(),
            "public-access": BoolField(True),
            "relationship-status": StringField(),
            "sports": StringField(),
            "status": StringField(),
            "website": StringField(),
            "work": StringField(),
        }

        parsed_fields = {
            (split := field.split(":", 1))[0].strip().lower(): split[1].strip()
            for field in (line.strip() for line in data.split("\n") if ":" in line)
            if not field.startswith("#")
        }

        for f in self.required, self.optional:
            for key, value in f.items():
                if not value:
                    continue

                value.update_value(parsed_fields.get(key))
                if value.default_value is not None:
                    continue

                match f:
                    case self.required:
                        raise ValueError(f'Required field "{key}" does not exist')
                    case self.optional:
                        f[key] = None
