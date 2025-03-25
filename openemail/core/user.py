# user.py
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
from dataclasses import dataclass
from datetime import date, datetime
from re import match
from typing import Generic, TypeVar, final

from gi.repository.GLib import base64_decode

from .crypto import Key, get_keys

T = TypeVar("T")


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
        """Attempt to update `self.value` from `data`."""


@final
class StringField(ProfileField[str]):
    """A profile field representing a string."""

    def __str__(self) -> str:
        return self.value

    def update_value(self, data: str | None) -> None:
        """Update `self.value` to `data`."""
        self.default_value = data


@final
class BoolField(ProfileField[bool]):
    """A profile field representing a boolean."""

    def __str__(self) -> str:
        return "Yes" if self.value else "No"

    def update_value(self, data: str | None) -> None:
        """Attempt to update `self.value` from `data`."""
        if data is not None:
            self.default_value = data == "Yes"


@final
class DateField(ProfileField[date]):
    """A profile field representing a date."""

    def __str__(self) -> str:
        return self.value.strftime("%x")

    def update_value(self, data: str | None) -> None:
        """Attempt to update `self.value` from `data`."""
        if not data:
            return

        try:
            self.default_value = date.fromisoformat(data)
        except ValueError:
            pass


@final
class DateTimeField(ProfileField[datetime]):
    """A profile field representing a date and time."""

    def __str__(self) -> str:
        return self.value.strftime("%c")

    def update_value(self, data: str | None) -> None:
        """Attempt to update `self.value` from `data`."""
        if not data:
            return

        try:
            self.default_value = datetime.fromisoformat(data)
        except ValueError:
            pass


@final
class KeyField(ProfileField[Key]):
    """A profile field representing a key."""

    def __str__(self) -> str:
        return str(self.value)

    def update_value(self, data: str | None) -> None:
        """Attempt to update `self.value` from `data`."""
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

        for fields in self.required, self.optional:
            for key, field in fields.items():
                if not field:
                    continue

                field.update_value(parsed_fields.get(key))

                if field.default_value is None:
                    match fields:
                        case self.required:
                            raise ValueError(f'Required field "{key}" does not exist')
                        case self.optional:
                            fields[key] = None


@dataclass(slots=True)
class User:
    """A local user."""

    address: Address

    public_encryption_key: Key
    private_encryption_key: Key

    public_signing_key: Key
    private_signing_key: Key

    def __init__(self, address: str, encryption_key: str, signing_key: str) -> None:
        """Try to create a local user for the provided `address` and Base64-encoded keys."""
        try:
            self.public_encryption_key, self.private_encryption_key = get_keys(
                encryption_key,
            )
            self.public_signing_key, self.private_signing_key = get_keys(
                signing_key,
            )
            self.address = Address(address)
        except ValueError as error:
            raise ValueError(
                "Attempt to construct local user with incorrect data."
            ) from error
