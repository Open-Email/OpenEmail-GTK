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
from urllib import parse, request
from urllib.error import HTTPError, URLError

from openemail.crypto import decrpyt_anonymous, get_nonce
from openemail.messages import Envelope, Message
from openemail.user import Address, Profile, User

setdefaulttimeout(5)

HEADERS = {"User-Agent": "Mozilla/5.0"}
EXCEPTIONS = (HTTPError, URLError, ValueError, TimeoutError)

__agents: dict[str, tuple[str, ...]] = {}


def get_agents(address: Address) -> tuple[str, ...]:
    """Get the first ≤3 responding mail agents for a given `address`."""
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
                contents = response.read().decode("utf-8")
                break
        except EXCEPTIONS:
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
                        method="HEAD",
                        headers=HEADERS,
                    ),
                )
            except EXCEPTIONS:
                agents.remove(agent)

        if agents:
            __agents[address.host_part] = tuple(agents[:3])

    return __agents.get(address.host_part) or (f"mail.{address.host_part}",)


def fetch_profile(address: Address) -> Profile | None:
    """Attempt to fetch the remote profile associated with a given `address`."""
    for agent in get_agents(address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/mail/{address.host_part}/{address.local_part}/profile",
                    headers=HEADERS,
                ),
            ) as response:
                try:
                    return Profile(response.read().decode("utf-8"))
                except ValueError:
                    continue
        except EXCEPTIONS:
            continue

    return None


def fetch_profile_image(address: Address) -> bytes | None:
    """Attempt to fetch the remote profile image associated with a given `address`."""
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
        except EXCEPTIONS:
            continue

    return None


def try_auth(user: User) -> bool:
    """Get whether authentication was successful for the given `user`."""
    for agent in get_agents(user.address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/home/{user.address.host_part}/{user.address.local_part}",
                    method="HEAD",
                    headers=HEADERS
                    | {
                        "Authorization": get_nonce(
                            agent,
                            user.public_signing_key,
                            user.private_signing_key,
                        )
                    },
                ),
            ):
                return True
        except EXCEPTIONS:
            continue

    return False


def fetch_contacts(user: User) -> tuple[Address, ...]:
    """Attempt to fetch the `user`'s contact list."""
    addresses = []

    for agent in get_agents(user.address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/home/{user.address.host_part}/{user.address.local_part}/links",
                    headers=HEADERS
                    | {
                        "Authorization": get_nonce(
                            agent,
                            user.public_signing_key,
                            user.private_signing_key,
                        )
                    },
                ),
            ) as response:
                contents = response.read().decode("utf-8")
        except EXCEPTIONS:
            continue

        if contents:
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


def fetch_envelope(
    url: str,
    message_id: str,
    user: User,
    author: Address,
) -> Envelope | None:
    """Perform a HEAD request to the specified URL and retrieves response headers.

    Args:
        url: The URL for the HEAD request
        message_id: The message ID
        user: Local user
        author: Address of the remote user whose message is being fetched

    """
    try:
        if not (host := parse.urlparse(url).hostname):
            return
    except ValueError:
        return None

    try:
        with request.urlopen(
            request.Request(
                url,
                method="HEAD",
                headers=HEADERS
                | {
                    "Authorization": get_nonce(
                        host,
                        user.public_signing_key,
                        user.private_signing_key,
                    )
                },
            ),
        ) as response:
            return Envelope(
                user,
                author,
                message_id,
            ).assign_header_values(response.headers)

    except EXCEPTIONS:
        return None


def fetch_message_from_agent(
    url: str,
    user: User,
    author: Address,
    message_id: str,
    broadcast_allowed: bool,
) -> Message | None:
    """Attempt to fetch a message from the provided `agent`."""
    # TODO

    if not (envelope := fetch_envelope(url, message_id, user, author)):
        return None

    try:
        envelope.open_content_headers()
    except ValueError:
        return None

    if envelope.is_broadcast and (not broadcast_allowed):
        return None

    try:
        if not (host := parse.urlparse(url).hostname):
            return
    except ValueError:
        return None

    try:
        with request.urlopen(
            request.Request(
                url,
                headers=HEADERS
                | {
                    "Authorization": get_nonce(
                        host,
                        user.public_signing_key,
                        user.private_signing_key,
                    )
                },
            ),
        ) as response:
            return Message(envelope, response.read().decode("utf-8"))
    except EXCEPTIONS:
        return None


def fetch_broadcast_ids(user: User, author: Address) -> tuple[str, ...]:
    """Attempt to fetch broadcast IDs by `author`."""
    for agent in get_agents(user.address):
        try:
            with request.urlopen(
                request.Request(
                    f"https://{agent}/mail/{author.host_part}/{author.local_part}/messages",
                    headers=HEADERS
                    | {
                        "Authorization": get_nonce(
                            agent,
                            user.public_signing_key,
                            user.private_signing_key,
                        )
                    },
                ),
            ) as response:
                contents = response.read().decode("utf-8")
        except EXCEPTIONS:
            continue

        if contents:
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
                url=f"https://{agent}/mail/{author.host_part}/{author.local_part}/messages/{message_id}",
                user=user,
                author=author,
                message_id=message_id,
                broadcast_allowed=True,
            ):
                messages.append(message)
                break

    return tuple(messages)
