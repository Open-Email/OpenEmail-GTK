# message.py
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

from base64 import b64decode
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import NamedTuple, Self

from openemail.crypto import decrypt_anonymous, decrypt_xchacha20poly1305
from openemail.user import Address, User, parse_headers


def generate_link(first: Address, second: Address) -> str:
    """Generate a connection identifier for `address_1` and `address_2`."""
    return sha256(
        f"{min(first, second)}{max(first, second)}".encode("ascii")
    ).hexdigest()


class AttachmentProperties(NamedTuple):
    """A file attached to a message."""

    name: str
    part: str | None


@dataclass(slots=True)
class Envelope:
    """Metadata about a message."""

    message_id: str
    headers: dict[str, str]
    user: User | None = None

    date: datetime = field(init=False)
    subject: str = field(init=False)
    author: Address = field(init=False)
    readers: list[Address] = field(init=False, default_factory=list)

    access_links: str | None = field(init=False, default=None)
    access_key: bytes | None = field(init=False, default=None)

    parent_id: str | None = field(init=False, default=None)
    part: int = field(init=False, default=0)
    file_name: str | None = field(init=False, default=None)
    files: dict[str, AttachmentProperties] = field(init=False, default_factory=dict)

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

        for key, value in self.headers.items():
            key, value = key.lower(), value.strip()

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

        if not message_headers:
            raise ValueError("Empty message headers.")

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
                raise ValueError("Unable to decode headers.") from error

        except (IndexError, KeyError, ValueError) as error:
            raise ValueError("Could not parse headers.") from error

        try:
            self.message_id = headers["id"]
            self.date = datetime.fromisoformat(headers["date"])
            self.subject = headers["subject"]
            self.author = Address(headers["author"])
        except KeyError as error:
            raise ValueError("Incomplete header contents.") from error

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
                except ValueError as error:
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
    contents: str | None = None
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
            except ValueError as error:
                pass

    def reconstruct_from_children(self) -> None:
        """Attempt to reconstruct the entire contents of this message from all of its children.

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

            # TODO: Check if "name" is how you're supposed to reconstruct these
            if not (attachment := self.attachments.get(child.envelope.file_name)):
                attachment = self.attachments[child.envelope.file_name] = []
            attachment.append(child)

        parts.sort(key=lambda part: part.envelope.part)
        for part in parts:
            self.contents = f"{self.contents or ''}{part.contents or ''}"

        for name, attachment in self.attachments.items():
            attachment.sort(key=lambda part: part.envelope.part)
