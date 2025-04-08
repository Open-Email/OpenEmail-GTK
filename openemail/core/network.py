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
import logging
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPResponse, InvalidURL
from os import getenv
from pathlib import Path
from socket import setdefaulttimeout
from typing import AsyncGenerator, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .crypto import (
    CHECKSUM_ALGORITHM,
    ENCRYPTION_ALGORITHM,
    SIGNING_ALGORITHM,
    decrypt_anonymous,
    decrypt_xchacha20poly1305,
    encrypt_anonymous,
    encrypt_xchacha20poly1305,
    fingerprint,
    get_nonce,
    random_bytes,
    random_string,
    sign_data,
)
from .message import Envelope, Message, Notification, generate_link
from .user import Address, Profile, User, parse_headers

cache_dir: Path = Path(getenv("XDG_CACHE_DIR", Path.home() / ".cache")) / "openemail"

_agents: dict[str, tuple[str, ...]] = {}

setdefaulttimeout(5)


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

    except (InvalidURL, URLError, HTTPError, TimeoutError, ValueError) as error:
        logging.debug(
            "%s, URL: %s, Method: %s, Authorization: %s",
            error,
            url,
            method or ("GET" if data else "POST"),
            bool(user),
        )

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

        index = 0
        async for agent in (
            stripped
            for line in contents.split("\n")
            if (stripped := line.strip()) and (not stripped.startswith("#"))
            if await request(_Mail(stripped, address).host, method="HEAD")
        ):
            if index > 2:
                break

            index += 1
            _agents[address.host_part] = _agents.get(address.host_part, ()) + (agent,)

        break

    return _agents.get(address.host_part, (f"mail.{address.host_part}",))


async def try_auth(user: User) -> bool:
    """Get whether authentication was successful for the given `user`."""
    logging.debug("Attempting authentication…")
    for agent in await get_agents(user.address):
        if await request(_Home(agent, user.address).home, user, method="HEAD"):
            logging.info("Authentication successful")
            return True

    logging.error("Authentication failed")
    return False


async def fetch_profile(address: Address) -> Profile | None:
    """Attempt to fetch the remote profile associated with a given `address`."""
    logging.debug("Fetching profile for %s…", address)
    for agent in await get_agents(address):
        if not (response := await request(_Mail(agent, address).profile)):
            continue

        with response:
            try:
                logging.debug("Profile fetched for %s", address)
                return Profile(address, response.read().decode("utf-8"))
            except UnicodeError:
                continue

            break

    logging.error("Could not fetch profile for %s", address)
    return None


async def update_profile(user: User, values: dict[str, str]) -> None:
    """Attempt to update `user`'s public profile with `values`."""
    logging.debug("Updating user profile…")

    values.update(
        {
            "Updated": datetime.now().isoformat(timespec="seconds"),
            "Encryption-Key": "; ".join(
                (
                    f"id={user.public_encryption_key.key_id or 0}",
                    f"algorithm={user.public_encryption_key.algorithm}",
                    f"value={user.public_encryption_key}",
                )
            ),
            "Signing-Key": "; ".join(
                (
                    f"algorithm={user.public_signing_key.algorithm}",
                    f"value={user.public_signing_key}",
                )
            ),
        }
    )

    data = (
        f"## Profile of {user.address}\n"
        + "\n".join((": ".join((k.title(), v))) for k, v in values.items() if v)
        + "\n##End of profile"
    ).encode("utf-8")

    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).profile,
            user,
            method="PUT",
            data=data,
        ):
            logging.info("Profile updated")
            return

    logging.error("Failed to update profile with values %s", values)


async def fetch_profile_image(address: Address) -> bytes | None:
    """Attempt to fetch the remote profile image associated with a given `address`."""
    logging.debug("Fetching profile image for %s…", address)
    for agent in await get_agents(address):
        if not (response := await request(_Mail(agent, address).image)):
            continue

        with response:
            logging.debug("Profile image fetched for %s", address)
            return response.read()
            break

    logging.warning("Could not fetch profile image for %s", address)
    return None


async def update_profile_image(user: User, image: bytes) -> None:
    """Attempt to upload `image` to be used as the user's profile image."""
    logging.debug("Updating profile image…")
    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).image,
            user,
            method="PUT",
            data=image,
        ):
            logging.info("Updated profile image.")
            return

    logging.error("Updating profile image failed.")


async def delete_profile_image(user: User) -> None:
    """Attempt to delete `user`'s profile image."""
    logging.debug("Deleting profile image…")
    for agent in await get_agents(user.address):
        if await request(_Home(agent, user.address).image, user, method="DELETE"):
            logging.info("Deleted profile image.")
            return

    logging.error("Deleting profile image failed.")


async def fetch_contacts(user: User) -> tuple[Address, ...]:
    """Attempt to fetch the `user`'s contact list."""
    logging.debug("Fetching contact list…")
    addresses = []

    for agent in await get_agents(user.address):
        if not (response := await request(_Home(agent, user.address).links, user)):
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
                contact = decrypt_anonymous(
                    parts[1].strip(),
                    user.private_encryption_key,
                    user.public_encryption_key,
                ).decode("utf-8")
            except ValueError:
                continue

            # For backwards-compatibility with contacts added before 1.0
            try:
                addresses.append(Address(contact))
            except (ValueError, UnicodeDecodeError):
                pass
            else:
                continue

            try:
                addresses.append(Address(parse_headers(contact)["address"]))
            except KeyError:
                continue

        break

    logging.debug("Contact list fetched")
    return tuple(addresses)


async def new_contact(address: Address, user: User) -> None:
    """Attempt to add `address` to the user's address book."""
    logging.debug("Adding %s to address book…", address)

    try:
        data = b64encode(
            encrypt_anonymous(
                f"address={address};broadcasts=yes".encode("utf-8"),
                user.public_encryption_key,
            )
        )
    except ValueError as error:
        logging.error(
            "Error adding %s to address book: Failed to encrypt address: %s",
            address,
            error,
        )
        return

    link = generate_link(address, user.address)
    for agent in await get_agents(address):
        if await request(
            _Link(agent, user.address, link).home,
            user,
            method="PUT",
            data=data,
        ):
            logging.info("Added %s to address book", address)
            return

    logging.error("Failed adding %s to address book", address)


async def delete_contact(address: Address, user: User) -> None:
    """Attempt to delete `address` from the user's address book."""
    logging.debug("Deleting contact %s…", address)
    link = generate_link(address, user.address)
    for agent in await get_agents(address):
        if await request(
            _Link(agent, user.address, link).home,
            user,
            method="DELETE",
        ):
            logging.info("Deleted contact %s", address)
            return

    logging.error("Deleting contact %s failed", address)


async def fetch_envelope(
    url: str, message_id: str, user: User, author: Address
) -> Envelope | None:
    """Perform a HEAD request to the specified URL and retrieve response headers.

    Args:
        url: The URL for the HEAD request
        message_id: The message ID
        user: Local user
        author: The remote user whose message is being fetched

    """
    logging.debug("Fetching envelope %s…", message_id[:8])
    if not (agent := urlparse(url).hostname):
        logging.error("Fetching envelope %s failed: Invalid URL", message_id[:8])
        return None

    if (envelope_path := cache_dir / "envelopes" / agent / message_id).is_file():
        headers = json.load(envelope_path.open("r"))
    else:
        if not (response := await request(url, user, method="HEAD")):
            logging.error("Fetching envelope %s failed", message_id[:8])
            return None

        headers = dict(response.getheaders())

        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(headers, envelope_path.open("w"))

    try:
        logging.debug("Fetched envelope %s", message_id[:8])
        return Envelope(message_id, headers, author, user)
    except ValueError as error:
        logging.error("Fetching envelope %s failed: %s", message_id[:8], error)
        return None


async def fetch_message_from_agent(
    url: str, user: User, author: Address, message_id: str
) -> Message | None:
    """Attempt to fetch a message from the provided agent `url`."""
    logging.debug("Fetching message %s…", message_id[:8])
    if not (agent := urlparse(url).hostname):
        logging.error("Fetching message %s failed: Invalid URL", message_id[:8])
        return None

    if not (envelope := await fetch_envelope(url, message_id, user, author)):
        return None

    if envelope.is_child:
        logging.debug("Fetched message %s", message_id[:8])
        return Message(envelope, attachment_url=url)

    if (message_path := cache_dir / "messages" / agent / message_id).is_file():
        contents = message_path.read_bytes()
    else:
        if not (response := await request(url, user)):
            logging.error(
                "Fetching message %s failed: Failed fetching body",
                message_id[:8],
            )
            return None

        with response:
            contents = response.read()

        message_path.parent.mkdir(parents=True, exist_ok=True)
        message_path.write_bytes(contents)

    if (not envelope.is_broadcast) and envelope.access_key:
        try:
            contents = decrypt_xchacha20poly1305(contents, envelope.access_key)
        except ValueError as error:
            logging.error(
                "Fetching message %s failed: Failed to decrypt body: %s",
                message_id[:8],
                error,
            )
            return None

    try:
        logging.debug("Fetched message %s", message_id[:8])
        return Message(envelope, contents.decode("utf-8"))
    except UnicodeError as error:
        logging.error(
            "Fetching message %s failed: Failed to decode body: %s",
            message_id[:8],
            error,
        )
        return None


async def fetch_message_ids(url: str, user: User, author: Address) -> tuple[str, ...]:
    """Attempt to fetch message IDs by `author`, addressed to `user` from `url`.

    `{}` in `url` will be substituted by the mail agent.
    """
    logging.debug("Fetching message IDs from %s…", author)
    for agent in await get_agents(user.address):
        if not (response := await request(url.format(agent), user)):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        logging.debug("Fetched message IDs from %s", author)
        return tuple(
            stripped for line in contents.split("\n") if (stripped := line.strip())
        )

    logging.warning("Could not fetch message IDs from %s", author)
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
                url.format(agent, message_id), user, author, message_id
            ):
                messages[message.envelope.message_id] = message
                break

    for message_id, message in messages.copy().items():
        if message.envelope.parent_id:
            if parent := messages.get(message.envelope.parent_id):
                parent.add_child(messages.pop(message_id))

    for message in messages.values():
        message.reconstruct_from_children()

    logging.debug("Fetched messages from %s", author)
    return tuple(messages.values())


async def fetch_broadcasts(user: User, author: Address) -> tuple[Message, ...]:
    """Attempt to fetch broadcasts by `author`."""
    logging.debug("Fetching broadcasts from %s…", author)
    return await fetch_messages(
        _Mail("{}", author).messages,
        _Mail("{}", author).messages + "/{}",
        user,
        author,
    )


async def fetch_link_messages(user: User, author: Address) -> tuple[Message, ...]:
    """Attempt to fetch messages by `author`, addressed to `user`."""
    logging.debug("Fetching link messages messages from %s…", author)
    link = generate_link(user.address, author)

    return await fetch_messages(
        _Link("{}", author, link).messages,
        _Link("{}", author, link).messages + "/{}",
        user,
        author,
    )


async def send_message(
    user: User,
    readers: Iterable[Address],
    subject: str,
    body: str,
    reply: str | None = None,
) -> None:
    """Attempt to send `message` to `readers`.

    If `readers` is empty, send a broadcast.

    `reply` is an optional `Subject-ID` of a thread that the message should be part of.
    """
    logging.debug("Sending message…")
    if not body:
        logging.warning("Failed sending message: Empty body")
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
                f"algorithm={CHECKSUM_ALGORITHM}",
                f"value={sha256(body_bytes).hexdigest()}",
            )
        ),
        "Subject": subject,
        "Subject-Id": reply or message_id,
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
                logging.error("Failed sending message: Could not fetch reader profiles")
                return

            try:
                groups.append(
                    ";".join(
                        (
                            f"link={generate_link(user.address, reader)}",
                            f"fingerprint={fingerprint(profile.required['signing-key'].value)}",
                            f"value={b64encode(encrypt_anonymous(access_key, key_field.value)).decode('utf-8')}",
                            f"id={key_id}",
                        )
                    )
                )
            except ValueError as error:
                logging.error("Error sending message: %s", error)
                return

        try:
            body_bytes = encrypt_xchacha20poly1305(body_bytes, access_key)
            headers_bytes = encrypt_xchacha20poly1305(headers_bytes, access_key)
        except ValueError as error:
            logging.error("Error sending message: %s", error)
            return

        headers.update(
            {
                "Message-Access": ",".join(groups),
                "Message-Encryption": ENCRYPTION_ALGORITHM,
                "Message-Headers": f"algorithm={ENCRYPTION_ALGORITHM};",
            }
        )

    headers["Message-Headers"] = (
        headers.get("Message-Headers", "")
        + f"value={b64encode(headers_bytes).decode('utf-8')}"
    )

    checksum_fields.sort()
    checksum = sha256(("".join(headers[f] for f in checksum_fields)).encode("utf-8"))

    try:
        signature = sign_data(user.private_signing_key, checksum.digest())
    except ValueError as error:
        logging.error("Error sending message: %s", error)
        return

    headers.update(
        {
            "Content-Length": str(len(body_bytes)),
            "Message-Checksum": ";".join(
                (
                    f"algorithm={CHECKSUM_ALGORITHM}",
                    f"order={':'.join(checksum_fields)}",
                    f"value={checksum.hexdigest()}",
                )
            ),
            "Message-Signature": ";".join(
                (
                    f"id={user.public_encryption_key.key_id or 0}",
                    f"algorithm={SIGNING_ALGORITHM}",
                    f"value={signature}",
                )
            ),
        }
    )

    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).messages,
            user,
            headers=headers,
            data=body_bytes,
        ):
            await notify_readers(readers, user)
            logging.info("Message sent successfully")
            return

    logging.error("Failed sending message")


async def notify_readers(readers: Iterable[Address], user: User) -> None:
    """Attempt to notify `readers` of a new message."""
    logging.debug("Notifying readers…")
    for reader in readers:
        if not (
            (profile := await fetch_profile(reader))
            and (key_field := profile.optional.get("encryption-key"))
        ):
            logging.warning(
                "Failed notifying notify %s: Could not fetch profile",
                reader,
            )
            continue

        try:
            address = b64encode(
                encrypt_anonymous(
                    str(user.address).encode("utf-8"),
                    key_field.value,
                )
            )
        except ValueError as error:
            logging.warning(
                "Error notifying %s: Failed to encrypt address: %s",
                reader,
                error,
            )
            continue

        link = generate_link(reader, user.address)
        for agent in await get_agents(reader):
            if await request(
                _Link(agent, reader, link).notifications,
                user,
                method="PUT",
                data=address,
            ):
                logging.debug("Notified %s", reader)
                break

        logging.warning("Failed notifying %s")


async def fetch_notifications(user: User) -> AsyncGenerator[Notification, None]:
    """Attempt to fetch all of `user`'s new notifications."""
    contents = None
    logging.debug("Fetching notifications…")
    for agent in await get_agents(user.address):
        if not (
            response := await request(
                _Home(agent, user.address).notifications,
                user,
            )
        ):
            continue

        contents = response.read().decode("utf-8")
        break

    if contents:
        for notification in contents.split("\n"):
            if not (stripped := notification.strip()):
                continue

            try:
                ident, link, signing_key_fp, encrypted_notifier = (
                    part.strip() for part in stripped.split(",", 4)
                )
            except IndexError:
                logging.debug("Invalid notification: %s", notification)
                continue

            # TODO: Store notifications, check if they were already processed

            try:
                notifier = Address(
                    decrypt_anonymous(
                        encrypted_notifier,
                        user.private_encryption_key,
                        user.public_encryption_key,
                    ).decode("utf-8")
                )
            except ValueError:
                logging.debug("Unable to decrypt notification: %s", notification)
                continue

            if not (profile := await fetch_profile(notifier)):
                logging.error(
                    "Failed to fetch notification: Could not fetch profile for %s",
                    notifier,
                )
                continue

            if not (
                signing_key_fp == fingerprint(profile.required["signing-key"].value)
            ) or (
                (last_signing_key := profile.optional.get("last-signing-key"))
                and (signing_key_fp == fingerprint(last_signing_key.value))
            ):
                logging.debug("Fingerprint mismatch for notification: %s", notification)
                continue

            yield Notification(ident, datetime.now(), link, notifier, signing_key_fp)

    logging.debug("Notifications fetched")


async def delete_message(
    message_id: str,
    user: User,
) -> bool:
    """Attempt to delete `message_id`.

    Returns `True` on success.
    """
    logging.debug("Deleting message %s…", message_id[:8])
    for agent in await get_agents(user.address):
        if await request(
            _Message(agent, user.address, message_id).message,
            user,
            method="DELETE",
        ):
            logging.info("Deleted message %s", message_id[:8])
            return True

    logging.error("Deleting message %s failed", message_id[:8])
    return False


@dataclass(slots=True)
class _Location:
    agent: str
    address: Address


@dataclass(slots=True)
class _Home(_Location):
    @property
    def home(self) -> str:
        return f"https://{self.agent}/home/{self.address.host_part}/{self.address.local_part}"

    @property
    def links(self) -> str:
        return f"{self.home}/links"

    @property
    def profile(self) -> str:
        return f"{self.home}/profile"

    @property
    def image(self) -> str:
        return f"{self.home}/image"

    @property
    def messages(self) -> str:
        return f"{self.home}/messages"

    @property
    def notifications(self) -> str:
        return f"{self.home}/notifications"


@dataclass(slots=True)
class _Mail(_Location):
    @property
    def host(self) -> str:
        return f"https://{self.agent}/mail/{self.address.host_part}"

    @property
    def mail(self) -> str:
        return f"{self.host}/{self.address.local_part}"

    @property
    def profile(self) -> str:
        return f"{self.mail}/profile"

    @property
    def image(self) -> str:
        return f"{self.mail}/image"

    @property
    def messages(self) -> str:
        return f"{self.mail}/messages"


@dataclass(slots=True)
class _Message(_Home):
    message_id: str

    @property
    def message(self) -> str:
        return f"{self.messages}/{self.message_id}"


@dataclass(slots=True)
class _Link(_Location):
    link: str

    @property
    def home(self) -> str:
        return f"{_Home(self.agent, self.address).home}/links/{self.link}"

    @property
    def mail(self) -> str:
        return f"{_Mail(self.agent, self.address).mail}/link/{self.link}"

    @property
    def messages(self) -> str:
        return f"{self.mail}/messages"

    @property
    def notifications(self) -> str:
        return f"{self.home}/notifications"
