# messages.py
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
from typing import Self

from openemail.user import Address, User


@dataclass(slots=True)
class ContentHeaders:
    message_id: str
    date: datetime
    subject: str
    subject_id: str
    checksum: str
    size: int
    author: Address
    # TODO


@dataclass(slots=True)
class Envelope:
    user: User
    author: Address
    message_id: str
    access_links: str | None = None
    stream_id: str | None = None

    payload_cipher: str | None = None

    headers_order: str | None = None
    headers_sum: str | None = None
    headers_signature: str | None = None

    content_headers: ContentHeaders | None = None
    content_header_bytes: bytes | None = None

    headers: dict[str, str] = field(default_factory=dict)
    envelope_data: bytes = b""

    headers_size: int = field(init=False, default=0)

    @property
    def is_broadcast(self) -> bool:
        return not self.access_links

    @staticmethod
    def parse_header_attributes(data: str) -> dict[str, str]:
        return dict(
            attr.strip().split("=", 1) for attr in data.split(";") if "=" in attr
        )

    def assign_header_values(self, headers: dict[str, str]) -> Self:
        # TODO
        for key, value in headers.items():
            if not (key := key.lower()).startswith("message-"):
                continue

            value = value.strip()

            self.headers_size += len(key + value)

            if self.headers_size > 524288:
                raise ValueError("Total size of headers exceeds the allowed maximum.")

            match key.removeprefix("message-"):
                case "id":
                    if self.message_id != value:
                        raise ValueError("Invalid Message-Id in headers.")

                case "stream":
                    self.stream_id = value

                case "id":
                    self.access_links = value

                case "headers":
                    content_headers = Envelope.parse_header_attributes(value)
                    if (algorithm := content_headers.get("algorithm")) and (
                        algorithm.lower() != "xchacha20poly1305"
                    ):
                        raise ValueError(f"Headers algorithm mismatch for {algorithm}.")

                    if data := content_headers.get("value"):
                        try:
                            self.content_header_bytes = b64decode(data)
                        except ValueError:
                            pass

                case "checksum":
                    checksum = Envelope.parse_header_attributes(value)
                    if (
                        (algorithm := checksum.get("algorithm"))
                        and (sum := checksum.get("value"))
                        and (order := checksum.get("order"))
                    ):
                        if algorithm.lower() != "sha256":
                            raise ValueError(
                                f'Checksum algorithm mismatch for "{algorithm}".'
                            )

                        self.headers_order = order
                        self.headers_sum = sum
                    else:
                        raise ValueError(f"Bad checksum: {checksum}.")

                case "signature":
                    signature = Envelope.parse_header_attributes(value)
                    if (algorithm := signature.get("algorithm")) and (
                        data := signature.get("value")
                    ):
                        if algorithm.lower() != "ed25519":
                            raise ValueError(
                                f'Signature algorithm mismatch for "{algorithm}".'
                            )

                        self.headers_signature = data

                case "encryption":
                    self.payload_cipher = value

                case _:
                    continue

            self.headers[key] = value
            self.envelope_data += b"{key}: {value}\n"

        return self

    def open_content_headers(self) -> None:
        if not self.content_header_bytes:
            raise ValueError("No content header bytes to open.")

        if self.is_broadcast:
            try:
                text = self.content_header_bytes.decode("utf-8")
            except ValueError as error:
                raise ValueError("Could not decode header bytes.") from error

            try:
                self.content_headers = content_from_headers(text)
            except ValueError as error:
                raise ValueError("Could not parse content headers.") from error
            return
        else:
            raise NotImplementedError  # TODO

    def assert_authenticity(self) -> bool:
        return True  # TODO


def content_from_headers(data: str) -> ContentHeaders:
    message_id: str | None = None
    date: datetime | None = None
    subject: str | None = None
    subject_id: str | None = None
    checksum: str | None = None
    size: int | None = None
    author: Address | None = None

    for header in data.split("\n"):
        if (
            len(
                parts := tuple(
                    stripped
                    for part in header.strip().split(":", 1)
                    if (stripped := part.strip())
                )
            )
            == 1
        ):
            continue

        key, value = parts[0].lower(), parts[1]
        match key:
            case "id":
                message_id = value

            case "date":
                try:
                    date = datetime.fromisoformat(value)
                except ValueError as error:
                    raise ValueError("Incorrect date format.") from error

            case "subject":
                subject = value

            case "subject-id":
                subject_id = value

            case "checksum":
                paresed_checksum = Envelope.parse_header_attributes(value)
                if (algorithm := paresed_checksum.get("algorithm")) and (
                    sum := paresed_checksum.get("value")
                ):
                    if algorithm.lower() != "sha256":
                        raise ValueError(
                            f'Checksum algorithm mismatch for "{algorithm}".'
                        )
                    checksum = sum
                else:
                    raise ValueError(f"Bad checksum: {paresed_checksum}.")

            case "size":
                try:
                    size = int(value)
                except ValueError as error:
                    raise ValueError(
                        f'Unable to parse payload size "{value}".'
                    ) from error

            case "author":
                try:
                    author = Address(value)
                except ValueError as error:
                    raise ValueError(f'Invalid Author address "{value}".') from error

            case _:
                ...  # TODO

    if not (
        message_id and date and subject and subject_id and checksum and size and author
    ):
        raise ValueError("Incomplete header contents.")

    return ContentHeaders(message_id, date, subject, subject_id, checksum, size, author)
