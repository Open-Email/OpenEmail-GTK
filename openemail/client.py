# client.py
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


from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from re import match
from socket import setdefaulttimeout
from typing import Generic, NamedTuple, TypeVar, final
from urllib import request
from urllib.error import HTTPError, URLError

setdefaulttimeout(1)

HEADERS = {"User-Agent": "Mozilla/5.0"}
T = TypeVar("T")


class Address:
    address: str
    local_part: str
    host_part: str

    def __init__(self, address: str) -> None:
        if not match(
            r"^[a-z0-9][a-z0-9\.\-_\+]{2,}@[a-z0-9.-]+\.[a-z]{2,}|xn--[a-z0-9]{2,}$",
            lowercased := address.lower(),
        ):
            raise ValueError(f'Email address "{address}" is invalid.')

        self.address = lowercased
        try:
            self.local_part, self.host_part = self.address.split("@")
        except ValueError as error:
            raise ValueError(
                f'Email address "{address}" contains more than a single @ character.'
            ) from error


class EncryptionKey(NamedTuple):
    id: str | None
    algorithm: str
    value: str


@dataclass
class ProfileField(Generic[T]):
    name: str | None = None
    default_value: T | None = None

    @property
    def value(self) -> T:
        if self.default_value is None:
            raise ValueError("Profile incorrectly initialized.")

        return self.default_value

    @property
    @abstractmethod
    def string(self) -> str: ...

    @abstractmethod
    def update_value(self, data: str | None) -> None: ...


@final
class StringField(ProfileField[str]):
    @property
    def string(self):
        return self.value

    def update_value(self, data):
        self.default_value = data


@final
class BoolField(ProfileField[bool]):
    @property
    def string(self):
        return _("Yes") if self.value else _("No")

    def update_value(self, data):
        if data is not None:
            self.default_value = data == "Yes"


@final
class DateField(ProfileField[date]):
    @property
    def string(self):
        return self.value.strftime("%x")

    def update_value(self, data):
        if not data:
            return

        try:
            self.default_value = date.fromisoformat(data)
        except ValueError:
            pass


@final
class DateTimeField(ProfileField[datetime]):
    @property
    def string(self):
        return self.value.strftime("%x")

    def update_value(self, data):
        if not data:
            return

        try:
            self.default_value = datetime.fromisoformat(data)
        except ValueError:
            pass


@final
class KeyField(ProfileField[EncryptionKey]):
    def update_value(self, data):
        if not data:
            return

        attrs = dict(
            attr.strip().split("=", 1) for attr in data.split(";") if "=" in attr
        )
        try:
            self.default_value = EncryptionKey(
                id=attrs.get("id"),
                algorithm=attrs["algorithm"],
                value=attrs["value"],
            )
        except KeyError:
            pass


class Profile:
    required: dict[str, ProfileField]
    optional: dict[str, ProfileField | None]

    def __init__(self, data: str) -> None:
        self.required = {
            # Represents the display name associated with the address.
            "name": StringField(_("Name")),
            "signing-key": StringField(),
            "updated": DateTimeField(),
        }

        self.optional = {
            # Provides a brief description or summary of the profile owner's background,
            # interests, or personal statement.
            "about": StringField(_("About")),
            # Indicates that the user may not read messages until the away status is removed.
            "away": BoolField(_("Away"), default_value=False),
            "away-warning": StringField(),
            # Indicates the date of birth of the profile owner
            "birthday": DateField(_("Birthday")),
            # Lists literary works or genres that the profile owner likes to read.
            "books": StringField(_("Books")),
            # Denotes the specific department or division
            # within the organization where the profile owner works.
            "department": StringField(_("Department")),
            # Provides information about the educational background of the profile owner,
            # including schools attended and degrees earned.
            "education": StringField(_("Education")),
            "encryption-key": KeyField(),
            # Represents the gender identity or gender expression of the profile owner.
            "gender": StringField(_("Gender")),
            # Lists hobbies, activities, or topics of interest
            # that the profile owner has indicated.
            "interests": StringField(_("Interests")),
            # Describes the job title or position held by the profile owner
            # within their organization.
            "job-title": StringField(_("Job Title")),
            # Indicates the languages spoken or understood by the profile owner.
            "languages": StringField(_("Languages")),
            "last-seen-public": BoolField(default_value=True),
            "last-signing-key": KeyField(),
            # May indicate the geographical location
            # such as address or GPS coordinates of the profile owner.
            "location": StringField(_("Location")),
            # Represents the physical address or mailing address of the profile owner.
            # Not to be confused with profile's Mail/HTTPS address.
            "mailing-address": StringField(_("Mailing Address")),
            # Lists films or movie genres that the profile owner enjoys.
            "movies": StringField(_("Movies")),
            # Indicates the profile owner's preferred music genres, artists, or songs.
            "music": StringField(_("Music")),
            # Allows for additional remarks or notes about the profile owner,
            # such as preferences, interests, or specific instructions.
            "notes": StringField(_("Notes")),
            # Denotes the name of the company, organization, or institution
            # the profile owner is affiliated with.
            "organization": StringField(_("Organization")),
            # The telephone contact numbers associated with the profile owner.
            "phone": StringField(_("Phone")),
            # Information about the profile owner's previous or current places of residence
            # or significant locations in their life.
            "place-slived": StringField(_("Places Lived")),
            "public-access": BoolField(default_value=True),
            # Indicates the current relationship status of the profile owner
            # (e.g., single, in a relationship, married, looking, etc.).
            "relationship-status": StringField(_("Relationship Status")),
            # May lists sports activities or teams
            # that the profile owner follows or participates in.
            "sports": StringField(_("Sports")),
            # Provides the current status message or context of the profile owner.
            "status": StringField(_("Status")),
            # Lists the website(s) associated with the profile owner.
            "website": StringField(_("Website")),
            # Provides details about the professional work experience of the profile owner.
            "work": StringField(_("Work")),
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
                            raise ValueError(f'Required field "{key}" does not exist.')
                        case self.optional:
                            fields[key] = None


__agents: dict[str, tuple[str, ...]] = {}


def __get_agents(address: Address) -> tuple[str, ...]:
    if existing := __agents.get(address.host_part):
        return existing

    contents = None
    for location in (
        f"https://{address.host_part}/.well-known/mail.txt",
        f"https://mail.{address.host_part}/.well-known/mail.txt",
    ):
        try:
            with request.urlopen(
                request.Request(location, headers=HEADERS),
            ) as response:
                contents = str(response.read().decode("utf-8"))
        except (HTTPError, URLError, ValueError):
            continue

    if contents:
        for agent in (
            agents := [
                stripped
                for line in contents.split("\n")
                if (stripped := line.strip()) and (not stripped.startswith("#"))
            ]
        ):
            try:
                request.urlopen(
                    request.Request(
                        f"https://{agent}/mail/{address.host_part}",
                        headers=HEADERS,
                        method="HEAD",
                    ),
                )
            except (HTTPError, URLError, ValueError):
                agents.remove(agent)

        if agents:
            __agents[address.host_part] = tuple(agents[:3])

    return __agents.get(address.host_part) or (f"mail.{address.host_part}",)


def fetch_profile(address: Address) -> Profile | None:
    for agent in __get_agents(address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/mail/{address.host_part}/{address.local_part}/profile",
                    headers=HEADERS,
                ),
            ) as response:
                try:
                    return Profile(str(response.read().decode("utf-8")))
                except ValueError:
                    continue
        except (HTTPError, URLError, ValueError):
            continue

    return None
