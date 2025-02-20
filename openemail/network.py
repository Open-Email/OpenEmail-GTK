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

from http.client import HTTPResponse
from socket import setdefaulttimeout
from typing import MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from openemail.crypto import decrpyt_anonymous, get_nonce
from openemail.message import Envelope, Message
from openemail.user import Address, Profile, User

setdefaulttimeout(5)

_agents: dict[str, tuple[str, ...]] = {}


def request(
    url: str,
    user: User | None = None,
    method: str | None = None,
) -> HTTPResponse | None:
    """Make an HTTP request using `urllib.urlopen`, handling errors and authentication.

    If `user` is set, use it and `url`'s host to obtain an authentication nonce.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if user:
            if not (agent := urlparse(url).hostname):
                return None

            headers.update(
                {
                    "Authorization": get_nonce(
                        agent,
                        user.public_signing_key,
                        user.private_signing_key,
                    )
                }
            )

        return urlopen(Request(url, headers=headers, method=method))

    except (HTTPError, URLError, ValueError, TimeoutError):
        return None


def get_agents(address: Address) -> tuple[str, ...]:
    """Get the first ≤3 responding mail agents for a given `address`."""
    if existing := _agents.get(address.host_part):
        return existing

    contents = None
    for location in (
        f"https://{address.host_part}/.well-known/mail.txt",
        f"https://mail.{address.host_part}/.well-known/mail.txt",
    ):
        if not (response := request(location)):
            continue

        with response:
            contents = response.read().decode("utf-8")

        for agent in (
            agents := [
                stripped
                for line in contents.split("\n")
                if (stripped := line.strip()) and (not stripped.startswith("#"))
            ]
        ):
            if not request(_mail_host(agent, address), method="HEAD"):
                agents.remove(agent)
                continue

        if agents:
            _agents[address.host_part] = tuple(agents[:3])

        break

    return _agents.get(address.host_part, (f"mail.{address.host_part}",))


def fetch_profile(address: Address) -> Profile | None:
    """Attempt to fetch the remote profile associated with a given `address`."""
    for agent in get_agents(address):
        if not (response := request(urljoin(_home(agent, address), "profile"))):
            continue

        with response:
            return Profile(response.read().decode("utf-8"))
            break

    return None


def fetch_profile_image(address: Address) -> bytes | None:
    """Attempt to fetch the remote profile image associated with a given `address`."""
    for agent in get_agents(address):
        if not (response := request(urljoin(_home(agent, address), "image"))):
            continue

        with response:
            return response.read()
            break

    return None


def try_auth(user: User) -> bool:
    """Get whether authentication was successful for the given `user`."""
    for agent in get_agents(user.address):
        if request(_home(agent, user.address), user, method="HEAD"):
            return True

    return False


def fetch_contacts(user: User) -> tuple[Address, ...]:
    """Attempt to fetch the `user`'s contact list."""
    addresses = []

    for agent in get_agents(user.address):
        if not (
            response := request(
                urljoin(_home(agent, user.address), "links"),
                user,
            )
        ):
            continue

        with response:
            contents = response.read().decode("utf-8")

        for line in contents.split("\n"):
            if len(parts := line.strip().split(",")) != 2:
                continue

            try:
                addresses.append(
                    Address(
                        decrpyt_anonymous(
                            parts[1].strip(),
                            user.private_encryption_key,
                            user.public_encryption_key,
                        ).decode("ascii")
                    )
                )
            except ValueError:
                continue
        break

    return tuple(addresses)


def fetch_envelope(url: str, message_id: str, user: User) -> Envelope | None:
    """Perform a HEAD request to the specified URL and retrieve response headers.

    Args:
        url: The URL for the HEAD request
        message_id: The message ID
        user: Local user

    """
    if not (response := request(url, user)):
        return None

    with response:
        try:
            return Envelope(message_id, response.headers)
        except ValueError:
            return None


def fetch_message_from_agent(
    url: str,
    user: User,
    message_id: str,
) -> Message | None:
    """Attempt to fetch a message from the provided `agent`."""
    if not (envelope := fetch_envelope(url, message_id, user)):
        return None

    if not (response := request(url, user)):
        return None

    with response:
        return Message(envelope, response.read().decode("utf-8"))


def fetch_broadcast_ids(user: User, author: Address) -> tuple[str, ...]:
    """Attempt to fetch broadcast IDs by `author`."""
    for agent in get_agents(user.address):
        if not (response := request(_messages(agent, author), user)):
            continue

        with response:
            contents = response.read().decode("utf-8")

        return tuple(
            stripped for line in contents.split("\n") if (stripped := line.strip())
        )

    return ()


def fetch_broadcasts(user: User, author: Address) -> tuple[Message, ...]:
    """Attempt to fetch broadcasts by `author`."""
    messages = []

    for message_id in fetch_broadcast_ids(user, author):
        for agent in get_agents(user.address):
            if message := fetch_message_from_agent(
                url=urljoin(_messages(agent, author), message_id),
                user=user,
                message_id=message_id,
            ):
                messages.append(message)
                break

    return tuple(messages)


def _home(agent: str, address: Address) -> str:
    return f"https://{agent}/home/{address.host_part}/{address.local_part}"


def _mail_host(agent: str, address: Address) -> str:
    return f"https://{agent}/mail/{address.host_part}/"


def _mail(agent: str, address: Address) -> str:
    return urljoin(_mail_host(agent, address), address.local_part)


def _messages(agent: str, address: Address) -> str:
    return urljoin(_mail(agent, address), "messages")
