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
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from http.client import HTTPMessage
from typing import Self

from openemail.crypto import decrypt_anonymous, decrypt_xchacha20poly1305
from openemail.user import Address, User, parse_headers


def generate_link(first: Address, second: Address) -> str:
    """Generate a connection identifier for `address_1` and `address_2`."""
    return sha256(
        f"{min(first, second)}{max(first, second)}".encode("ascii")
    ).hexdigest()


@dataclass(slots=True)
class Envelope:
    """Metadata about a message."""

    message_id: str
    headers: HTTPMessage
    user: User | None = None

    date: datetime = field(init=False)
    subject: str = field(init=False)
    author: Address = field(init=False)
    readers: list[Address] = field(init=False, default_factory=list)

    access_links: str | None = field(init=False, default=None)
    access_key: bytes | None = field(init=False, default=None)

    parent_id: str | None = field(init=False, default=None)
    file_name: str | None = field(init=False, default=None)

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
        # TODO: The macOS client does not implement this header and relies on Files instead
        if (file := headers.get("file")) and (file_headers := parse_headers(file)):
            self.file_name = file_headers.get("name")

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
