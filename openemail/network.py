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

import asyncio
import json
from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPResponse
from os import getenv
from pathlib import Path
from socket import setdefaulttimeout
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from openemail.crypto import (
    decrypt_anonymous,
    decrypt_xchacha20poly1305,
    encrypt_anonymous,
    encrypt_xchacha20poly1305,
    get_nonce,
    random_bytes,
    random_string,
    sign_data,
)
from openemail.message import Envelope, Message, generate_link
from openemail.user import Address, Profile, User

setdefaulttimeout(5)

cache_dir: Path = Path(getenv("XDG_CACHE_DIR", Path.home() / ".cache")) / "openemail"

_agents: dict[str, tuple[str, ...]] = {}


async def request(
    url: str,
    user: User | None = None,
    method: str | None = None,
    headers: dict[str, str] = {},
    data: bytes | None = None,
) -> HTTPResponse | None:
    """Make an HTTP request using `urllib.urlopen`, handling errors and authentication.

    If `user` is set, use it and `url`'s host to obtain an authentication nonce.
    """
    headers["User-Agent"] = "Mozilla/5.0"

    try:
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

        return await asyncio.to_thread(
            urlopen, Request(url, method=method, headers=headers, data=data)
        )

    except (HTTPError, URLError, ValueError, TimeoutError):
        return None


async def get_agents(address: Address) -> tuple[str, ...]:
    """Get the first ≤3 responding mail agents for a given `address`."""
    if existing := _agents.get(address.host_part):
        return existing

    contents = None
    for location in (
        f"https://{address.host_part}/.well-known/mail.txt",
        f"https://mail.{address.host_part}/.well-known/mail.txt",
    ):
        if not (response := await request(location)):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        for agent in (
            agents := [
                stripped
                for line in contents.split("\n")
                if (stripped := line.strip()) and (not stripped.startswith("#"))
            ]
        ):
            if not await request(_mail_host(agent, address), method="HEAD"):
                agents.remove(agent)
                continue

        if agents:
            _agents[address.host_part] = tuple(agents[:3])

        break

    return _agents.get(address.host_part, (f"mail.{address.host_part}",))


async def try_auth(user: User) -> bool:
    """Get whether authentication was successful for the given `user`."""
    for agent in await get_agents(user.address):
        if await request(_home(agent, user.address), user, method="HEAD"):
            return True

    return False


async def fetch_profile(address: Address) -> Profile | None:
    """Attempt to fetch the remote profile associated with a given `address`."""
    for agent in await get_agents(address):
        if not (response := await request(f"{_mail(agent, address)}/profile")):
            continue

        with response:
            try:
                return Profile(address, response.read().decode("utf-8"))
            except UnicodeError:
                continue

            break

    return None


async def fetch_profile_image(address: Address) -> bytes | None:
    """Attempt to fetch the remote profile image associated with a given `address`."""
    for agent in await get_agents(address):
        if not (response := await request(f"{_mail(agent, address)}/image")):
            continue

        with response:
            return response.read()
            break

    return None


async def fetch_contacts(user: User) -> tuple[Address, ...]:
    """Attempt to fetch the `user`'s contact list."""
    addresses = []

    for agent in await get_agents(user.address):
        if not (
            response := await request(
                f"{_home(agent, user.address)}/links",
                user,
            )
        ):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        for line in contents.split("\n"):
            if len(parts := line.strip().split(",")) != 2:
                continue

            try:
                addresses.append(
                    Address(
                        decrypt_anonymous(
                            parts[1].strip(),
                            user.private_encryption_key,
                            user.public_encryption_key,
                        ).decode("utf-8")
                    )
                )
            except (ValueError, UnicodeDecodeError):
                continue
        break

    return tuple(addresses)


async def fetch_envelope(url: str, message_id: str, user: User) -> Envelope | None:
    """Perform a HEAD request to the specified URL and retrieve response headers.

    Args:
        url: The URL for the HEAD request
        message_id: The message ID
        user: Local user
        author: The remote user whose message is being fetched

    """
    if not (agent := urlparse(url).hostname):
        return None

    if (envelope_path := cache_dir / "envelopes" / agent / message_id).is_file():
        headers = json.load(envelope_path.open("r"))
    else:
        if not (response := await request(url, user, method="HEAD")):
            return None

        headers = dict(response.getheaders())

        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(headers, envelope_path.open("w"))

    try:
        return Envelope(message_id, headers, user)
    except ValueError:
        return None


async def fetch_message_from_agent(
    url: str, user: User, message_id: str
) -> Message | None:
    """Attempt to fetch a message from the provided `agent`."""
    if not (envelope := await fetch_envelope(url, message_id, user)):
        return None

    if envelope.is_child:  # TODO: This probably won't work for split messages
        return Message(envelope, attachment_url=url)

    if not (agent := urlparse(url).hostname):
        return None

    if (message_path := cache_dir / "messages" / agent / message_id).is_file():
        contents = message_path.read_bytes()
    else:
        if not (response := await request(url, user)):
            return None

        with response:
            contents = response.read()

        message_path.parent.mkdir(parents=True, exist_ok=True)
        message_path.write_bytes(contents)

    if (not envelope.is_broadcast) and envelope.access_key:
        try:
            contents = decrypt_xchacha20poly1305(contents, envelope.access_key)
        except ValueError:
            return None

    try:
        return Message(envelope, contents.decode("utf-8"))
    except UnicodeError:
        return None


async def fetch_message_ids(url: str, user: User, author: Address) -> tuple[str, ...]:
    """Attempt to fetch message IDs by `author`, addressed to `user` from `url`.

    `{}` in `url` will be substituted by the mail agent.
    """
    for agent in await get_agents(user.address):
        if not (response := await request(url.format(agent), user)):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        return tuple(
            stripped for line in contents.split("\n") if (stripped := line.strip())
        )

    return ()


async def fetch_messages(
    id_url: str,
    url: str,
    user: User,
    author: Address,
) -> tuple[Message, ...]:
    """Attempt to fetch messages by `author` from `url` with IDs at `id_url`.

    `{}` in `id_url` will be substituted by the mail agent.

    The first two `{}`s in `url` will be substituted by the mail agent and the message ID.
    """
    messages: dict[str, Message] = {}
    for message_id in await fetch_message_ids(id_url, user, author):
        for agent in await get_agents(user.address):
            if message := await fetch_message_from_agent(
                url.format(agent, message_id), user, message_id
            ):
                messages[message.envelope.message_id] = message
                break

    for message_id, message in messages.copy().items():
        if message.envelope.parent_id:
            if parent := messages.get(message.envelope.parent_id):
                parent.add_child(messages.pop(message_id))

    for message in messages.values():
        message.reconstruct_from_children()

    return tuple(messages.values())


async def fetch_broadcasts(user: User, author: Address) -> tuple[Message, ...]:
    """Attempt to fetch broadcasts by `author`."""
    return await fetch_messages(
        _mail_messages("{}", author),
        _mail_messages("{}", author) + "/{}",
        user,
        author,
    )


async def fetch_link_messages(user: User, author: Address) -> tuple[Message, ...]:
    """Attempt to fetch messages by `author`, addressed to `user`."""
    link = generate_link(user.address, author)

    return await fetch_messages(
        _link_messages("{}", author, link),
        _link_messages("{}", author, link) + "/{}",
        user,
        author,
    )


async def send_message(
    user: User,
    readers: Iterable[Address],
    subject: str,
    body: str,
) -> None:
    """Attempt to send `message` to `readers`.

    If `readers` is empty, send a broadcast.
    """
    if not body:
        return

    body_bytes = body.encode("utf-8")
    message_id = sha256(
        "".join(
            (
                random_string(length=24),
                user.address.host_part,
                user.address.local_part,
            )
        ).encode("utf-8")
    ).hexdigest()

    checksum_fields = ["Message-Id", "Message-Headers"]
    headers: dict[str, str] = {
        "Message-Id": message_id,
        "Content-Type": "application/octet-stream",
    }
    content_headers: dict[str, str] = {
        "Id": message_id,
        "Author": str(user.address),
        "Date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "Size": str(len(body)),
        "Checksum": ";".join(
            (
                "algorithm=sha256",
                f"value={sha256(body_bytes).hexdigest()}",
            )
        ),
        "Subject": subject,
        "Subject-Id": message_id,
        "Category": "personal",
    }

    if readers:
        content_headers["Readers"] = ",".join((str(reader) for reader in readers))

    headers_bytes = "\n".join(
        (":".join((key, value)) for key, value in content_headers.items())
    ).encode("utf-8")

    if readers:
        checksum_fields += ("Message-Encryption", "Message-Access")
        access_key = random_bytes(32)

        groups: list[str] = []
        for reader in (*readers, user.address):
            if not (
                (profile := await fetch_profile(reader))
                and (key_field := profile.optional.get("encryption-key"))
                and (key_id := key_field.value.key_id)
            ):
                return

            try:
                groups.append(
                    ";".join(
                        (
                            f"link={generate_link(user.address, reader)}",
                            f"fingerprint={sha256(bytes(profile.required['signing-key'].value)).hexdigest()}",
                            f"value={b64encode(encrypt_anonymous(access_key, key_field.value)).decode('utf-8')}",
                            f"id={key_id}",
                        )
                    )
                )
            except ValueError:
                return

        try:
            body_bytes = encrypt_xchacha20poly1305(body_bytes, access_key)
            headers_bytes = encrypt_xchacha20poly1305(headers_bytes, access_key)
        except ValueError:
            return

        headers.update(
            {
                "Message-Access": ",".join(groups),
                "Message-Encryption": "xchacha20poly1305",
                "Message-Headers": "algorithm=xchacha20poly1305;",
            }
        )

    headers["Message-Headers"] = (
        headers.get("Message-Headers", "")
        + f"value={b64encode(headers_bytes).decode('utf-8')}"
    )

    checksum_fields.sort()
    checksum = sha256(
        ("".join(headers[field] for field in checksum_fields)).encode("utf-8")
    )

    try:
        signature = sign_data(user.private_signing_key, checksum.digest())
    except ValueError:
        return

    headers.update(
        {
            "Content-Length": str(len(body_bytes)),
            "Message-Checksum": ";".join(
                (
                    "algorithm=sha256",
                    f"order={':'.join(checksum_fields)}",
                    f"value={checksum.hexdigest()}",
                )
            ),
            "Message-Signature": ";".join(
                (
                    f"id={user.public_encryption_key.key_id or ''}",
                    "algorithm=ed25519",
                    f"value={signature}",
                )
            ),
        }
    )

    for agent in await get_agents(user.address):
        if await request(
            _home_messages(agent, user.address),
            user,
            method="POST",
            headers=headers,
            data=body_bytes,
        ):
            await notify_readers(readers, user)
            break


async def notify_readers(readers: Iterable[Address], user: User) -> None:
    """Attempt to notify `readers` of a new message."""
    for reader in readers:
        if not (
            (profile := await fetch_profile(reader))
            and (key_field := profile.optional.get("encryption-key"))
        ):
            continue

        try:
            address = b64encode(
                encrypt_anonymous(
                    str(user.address).encode("utf-8"),
                    key_field.value,
                )
            )
        except ValueError:
            continue

        link = generate_link(reader, user.address)
        for agent in await get_agents(reader):
            if await request(
                _notifications(agent, reader, link),
                user,
                method="PUT",
                data=address,
            ):
                break


async def delete_message(
    message_id: str,
    user: User,
) -> bool:
    """Attempt to delete `message_id`.

    Returns `True` on success.
    """
    for agent in await get_agents(user.address):
        if await request(
            f"{_home_messages(agent, user.address)}/{message_id}",
            user,
            method="DELETE",
        ):
            return True

    return False


def _home(agent: str, address: Address) -> str:
    return f"https://{agent}/home/{address.host_part}/{address.local_part}"


def _home_messages(agent: str, address: Address) -> str:
    return f"{_home(agent, address)}/messages"


def _mail_host(agent: str, address: Address) -> str:
    return f"https://{agent}/mail/{address.host_part}"


def _mail(agent: str, address: Address) -> str:
    return f"{_mail_host(agent, address)}/{address.local_part}"


def _mail_messages(agent: str, address: Address) -> str:
    return f"{_mail(agent, address)}/messages"


def _link(agent: str, address: Address, link: str) -> str:
    return f"{_mail(agent, address)}/link/{link}"


def _link_messages(agent: str, address: Address, link: str) -> str:
    return f"{_link(agent, address, link)}/messages"


def _notifications(agent: str, address: Address, link: str) -> str:
    return f"{_link(agent, address, link)}/notifications"
