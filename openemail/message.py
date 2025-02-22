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
from http.client import HTTPMessage
from typing import NamedTuple, Self

from openemail.user import Address, User


@dataclass(slots=True)
class Envelope:
    """Metadata about a message."""

    message_id: str
    headers: HTTPMessage

    date: datetime = field(init=False)
    subject: str = field(init=False)
    author: Address = field(init=False)

    def __post_init__(self) -> None:
        for key, value in self.headers.items():
            key, value = key.lower(), value.strip()

            match key:
                case "message-headers":
                    try:
                        headers = {
                            (split := header.split(":", 1))[0].lower(): split[1].strip()
                            for header in b64decode(
                                dict(
                                    attr.strip().split("=", 1)
                                    for attr in value.split(";")
                                )["value"]
                            )
                            .decode("utf-8")
                            .split("\n")
                        }

                        self.date = datetime.fromisoformat(headers["date"])
                        self.subject = headers["subject"]
                        self.author = Address(headers["author"])
                        return

                    except (IndexError, KeyError, ValueError) as error:
                        raise ValueError("Could not parse headers.") from error

        raise ValueError("Incomplete header contents.")


class Message(NamedTuple):
    """An envelope and its contents."""

    envelope: Envelope
    message: str
