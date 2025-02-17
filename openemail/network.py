# network.py
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

from socket import setdefaulttimeout
from urllib import request
from urllib.error import HTTPError, URLError

from openemail.user import Address, Profile

setdefaulttimeout(5)

HEADERS = {"User-Agent": "Mozilla/5.0"}
__agents: dict[str, tuple[str, ...]] = {}


def get_agents(address: Address) -> tuple[str, ...]:
    """Returns the first ≤3 responding mail agents for a given `address`."""
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
                break
        except (HTTPError, URLError, ValueError, TimeoutError):
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
            except (HTTPError, URLError, ValueError, TimeoutError):
                agents.remove(agent)

        if agents:
            __agents[address.host_part] = tuple(agents[:3])

    return __agents.get(address.host_part) or (f"mail.{address.host_part}",)


def fetch_profile(address: Address) -> Profile | None:
    """Attempts to fetch the remote profile associated with a given `address`."""
    for agent in get_agents(address):
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
        except (HTTPError, URLError, ValueError, TimeoutError):
            continue

    return None


def fetch_profile_image(address: Address) -> bytes | None:
    """Attempts to fetch the remote profile image associated with a given `address`."""
    for agent in get_agents(address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/mail/{address.host_part}/{address.local_part}/image",
                    headers=HEADERS,
                ),
            ) as response:
                try:
                    return response.read()
                except ValueError:
                    continue
        except (HTTPError, URLError, ValueError, TimeoutError):
            continue

    return None
