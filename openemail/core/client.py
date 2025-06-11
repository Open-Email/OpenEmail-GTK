# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import asyncio
import json
import logging
from base64 import b64encode
from collections.abc import AsyncGenerator, Generator, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from http.client import HTTPResponse, InvalidURL
from json import JSONDecodeError
from os import getenv
from pathlib import Path
from shutil import rmtree
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import crypto, model
from .model import (
    Address,
    AttachmentProperties,
    IncomingMessage,
    Message,
    Notification,
    Profile,
    User,
)

MAX_AGENTS = 3
MAX_MESSAGE_SIZE = 64_000_000
MAX_PROFILE_SIZE = 64_000
MAX_PROFILE_IMAGE_SIZE = 640_000

_SHORT = 8

logger = logging.getLogger(__name__)
data_dir = Path(getenv("XDG_DATA_DIR", Path.home() / ".local" / "share"), "openemail")
user = User()


class WriteError(Exception):
    """Raised if writing to the server fails."""


class _Home:
    def __init__(self, agent: str, address: Address) -> None:
        self.home = f"https://{agent}/home/{address.host_part}/{address.local_part}"
        self.links = f"{self.home}/links"
        self.profile = f"{self.home}/profile"
        self.image = f"{self.home}/image"
        self.messages = f"{self.home}/messages"
        self.notifications = f"{self.home}/notifications"


class _Message(_Home):
    def __init__(self, agent: str, address: Address, ident: str) -> None:
        super().__init__(agent, address)
        self.message = f"{self.messages}/{ident}"


class _Mail:
    def __init__(self, agent: str, address: Address) -> None:
        self.host = f"https://{agent}/mail/{address.host_part}"
        self.mail = f"{self.host}/{address.local_part}"
        self.profile = f"{self.mail}/profile"
        self.image = f"{self.mail}/image"
        self.messages = f"{self.mail}/messages"


class _Account:
    def __init__(self, agent: str, address: Address) -> None:
        self.account = (
            f"https://{agent}/account/{address.host_part}/{address.local_part}"
        )


class _Link:
    def __init__(self, agent: str, address: Address, link: str) -> None:
        self.home = f"{_Home(agent, address).home}/links/{link}"
        self.mail = f"{_Mail(agent, address).mail}/link/{link}"
        self.messages = f"{self.mail}/messages"
        self.notifications = f"{self.mail}/notifications"


async def request(
    url: str,
    *,
    auth: bool = False,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    max_length: int | None = None,
) -> HTTPResponse | None:
    """Make an HTTPS request, handling errors and authentication."""
    headers = headers or {}
    headers["User-Agent"] = "Mozilla/5.0"

    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return None

        if auth:
            if not (agent := parsed.hostname):
                return None

            headers.update(
                {"Authorization": crypto.get_nonce(agent, user.signing_keys)}
            )

        response = await asyncio.to_thread(
            urlopen, Request(url, method=method, headers=headers, data=data)
        )
    except (InvalidURL, URLError, HTTPError, TimeoutError, ValueError) as error:
        logger.debug(
            "%s, URL: %s, Method: %s, Authorization: %s",
            error,
            url,
            method or ("POST" if data else "GET"),
            auth,
        )
        return None

    if max_length:
        try:
            length = int(response.headers.get("Content-Length", 0))
        except ValueError:
            return response

        if length > max_length:
            logger.debug("Content-Length for %s exceeds max_length", url)
            return None

    return response


_agents: dict[str, tuple[str, ...]] = {}


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

        index = 1
        async for agent in (
            stripped
            for line in contents.split("\n")
            if (stripped := line.strip()) and (not stripped.startswith("#"))
            if await request(_Mail(stripped, address).host, method="HEAD")
        ):
            if index > MAX_AGENTS:
                break

            _agents[address.host_part] = (*_agents.get(address.host_part, ()), agent)
            index += 1

        break

    return _agents.get(address.host_part, (f"mail.{address.host_part}",))


async def try_auth() -> bool:
    """Try authenticating with `client.user`.

    Returns whether the attempt was successful.
    """
    logger.info("Authenticating…")
    for agent in await get_agents(user.address):
        if await request(_Home(agent, user.address).home, auth=True, method="HEAD"):
            logger.info("Authentication successful")
            return True

    logger.error("Authentication failed")
    return False


async def register() -> bool:
    """Try registering `client.user` and return whether the attempt was successful."""
    logger.info("Registering…")

    data = "\n".join(
        (
            f"Name: {user.address.local_part}",
            "Encryption-Key: "
            + ";".join(
                (
                    f"id={user.encryption_keys.public.key_id}",
                    f"algorithm={crypto.ANONYMOUS_ENCRYPTION_CIPHER}",
                    f"value={user.encryption_keys.public}",
                )
            ),
            "Signing-Key: "
            + ";".join(
                (
                    f"algorithm={crypto.SIGNING_ALGORITHM}",
                    f"value={user.signing_keys.public}",
                )
            ),
            f"Updated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        )
    ).encode("utf-8")

    for agent in await get_agents(user.address):
        if await request(_Account(agent, user.address).account, auth=True, data=data):
            logger.info("Authentication successful")
            return True

    # TODO: More descriptive errors
    logger.error("Registration failed")
    return False


async def fetch_profile(address: Address) -> Profile | None:
    """Fetch the remote profile associated with a given `address`."""
    logger.debug("Fetching profile for %s…", address)
    for agent in await get_agents(address):
        if not (response := await request(_Mail(agent, address).profile)):
            continue

        with response:
            try:
                logger.debug("Profile fetched for %s", address)
                return Profile(address, response.read(MAX_PROFILE_SIZE).decode("utf-8"))
            except UnicodeError:
                continue

            break

    logger.error("Could not fetch profile for %s", address)
    return None


async def update_profile(values: dict[str, str]) -> None:
    """Update `client.user`'s public profile with `values`."""
    logger.debug("Updating user profile…")

    values.update(
        {
            "Updated": datetime.now(UTC).isoformat(timespec="seconds"),
            "Encryption-Key": "; ".join(
                (
                    f"id={user.encryption_keys.public.key_id or 0}",
                    f"algorithm={user.encryption_keys.public.algorithm}",
                    f"value={user.encryption_keys.public}",
                )
            ),
            "Signing-Key": "; ".join(
                (
                    f"algorithm={user.signing_keys.public.algorithm}",
                    f"value={user.signing_keys.public}",
                )
            ),
        }
    )

    data = (
        f"## Profile of {user.address}\n"
        + "\n".join((f"{k.title()}: {v}") for k, v in values.items() if v)
        + "\n##End of profile"
    ).encode("utf-8")

    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).profile,
            auth=True,
            method="PUT",
            data=data,
        ):
            logger.info("Profile updated")
            return

    logger.error("Failed to update profile with values %s", values)
    raise WriteError


async def fetch_profile_image(address: Address) -> bytes | None:
    """Fetch the remote profile image associated with a given `address`."""
    logger.debug("Fetching profile image for %s…", address)
    for agent in await get_agents(address):
        if not (
            response := await request(
                _Mail(agent, address).image,
                max_length=MAX_PROFILE_IMAGE_SIZE,
            )
        ):
            continue

        with response:
            logger.debug("Profile image fetched for %s", address)
            return response.read()
            break

    logger.warning("Could not fetch profile image for %s", address)
    return None


async def update_profile_image(image: bytes) -> None:
    """Upload `image` to be used as `client.user`'s profile image."""
    logger.debug("Updating profile image…")
    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).image,
            auth=True,
            method="PUT",
            data=image,
        ):
            logger.info("Updated profile image.")
            return

    logger.error("Updating profile image failed.")
    raise WriteError


async def delete_profile_image() -> None:
    """Delete `client.user`'s profile image."""
    logger.debug("Deleting profile image…")
    for agent in await get_agents(user.address):
        if await request(_Home(agent, user.address).image, auth=True, method="DELETE"):
            logger.info("Deleted profile image.")
            return

    logger.error("Deleting profile image failed.")
    raise WriteError


async def fetch_contacts() -> set[tuple[Address, bool]]:
    """Fetch `client.user`'s contacts.

    Returns their addresses and whether broadcasts should be received from them.
    """
    logger.debug("Fetching contact list…")
    addresses = []

    for agent in await get_agents(user.address):
        if not (response := await request(_Home(agent, user.address).links, auth=True)):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        for line in contents.split("\n"):
            try:
                contact = crypto.decrypt_anonymous(
                    line.strip().split(",")[1].strip(),
                    user.encryption_keys.private,
                ).decode("utf-8")
            except (KeyError, ValueError):
                continue

            # For backwards-compatibility with contacts added before 1.0
            try:
                addresses.append((Address(contact), True))
                continue
            except (ValueError, UnicodeDecodeError):
                pass

            try:
                addresses.append(
                    (
                        Address((entry := model.parse_headers(contact))["address"]),
                        entry.get("broadcasts", "yes").lower() != "no",
                    )
                )
            except (KeyError, ValueError):
                continue

        break

    logger.debug("Contact list fetched")
    return set(addresses)


async def new_contact(address: Address, *, receive_broadcasts: bool = True) -> Profile:
    """Add `address` to `client.user`'s address book.

    Returns `address`'s profile on success.
    """
    logger.debug("Adding %s to address book…", address)

    try:
        data = b64encode(
            crypto.encrypt_anonymous(
                ";".join(
                    (
                        f"address={address}",
                        f"broadcasts={'Yes' if receive_broadcasts else 'No'}",
                    )
                ).encode("utf-8"),
                user.encryption_keys.public,
            )
        )
    except ValueError:
        logger.exception("Error adding %s to address book: Failed to encrypt", address)
        raise

    if not (profile := await fetch_profile(address)):
        logger.error("Failed adding %s to address book: No profile found")
        raise WriteError

    link = model.generate_link(address, user.address)
    for agent in await get_agents(address):
        if await request(
            _Link(agent, user.address, link).home,
            auth=True,
            method="PUT",
            data=data,
        ):
            logger.info("Added %s to address book", address)
            return profile

    logger.error("Failed adding %s to address book", address)
    raise WriteError


async def delete_contact(address: Address) -> None:
    """Delete `address` from `client.user`'s address book."""
    logger.debug("Deleting contact %s…", address)
    link = model.generate_link(address, user.address)
    for agent in await get_agents(address):
        if await request(
            _Link(agent, user.address, link).home,
            auth=True,
            method="DELETE",
        ):
            logger.info("Deleted contact %s", address)
            return

    logger.error("Deleting contact %s failed", address)
    raise WriteError


async def fetch_broadcasts(
    author: Address, *, exclude: Iterable[str] = ()
) -> tuple[IncomingMessage, ...]:
    """Fetch broadcasts by `author`, without messages with IDs in `exclude`."""
    logger.debug("Fetching broadcasts from %s…", author)
    return await _fetch_messages(author, broadcasts=True, exclude=exclude)


async def fetch_link_messages(
    author: Address, *, exclude: Iterable[str] = ()
) -> tuple[IncomingMessage, ...]:
    """Fetch messages by `author`, addressed to `client.user`.

    `exclude` are Message-Ids to ignore.
    """
    logger.debug("Fetching link messages messages from %s…", author)
    return await _fetch_messages(author, exclude=exclude)


async def fetch_outbox() -> tuple[IncomingMessage, ...]:
    """Fetch messages by `client.user`."""
    logger.debug("Fetching outbox…")
    return await _fetch_messages(user.address)


async def download_attachment(parts: Iterable[Message]) -> bytes | None:
    """Download and reconstruct an attachment from `parts`."""
    data = b""
    for part in parts:
        if not (
            part.attachment_url
            and (
                response := await request(
                    part.attachment_url,
                    auth=not part.is_broadcast,
                )
            )
        ):
            return None

        with response:
            contents = response.read()

        if part and (not part.is_broadcast) and part.access_key:
            try:
                contents = crypto.decrypt_xchacha20poly1305(contents, part.access_key)
            except ValueError:
                return None

        data += contents

    return data


def generate_message_id() -> str:
    """Generate a unique ID for a new message."""
    return sha256(
        "".join(
            (
                crypto.random_string(length=24),
                user.address.host_part,
                user.address.local_part,
            )
        ).encode("utf-8")
    ).hexdigest()


async def notify_readers(readers: Iterable[Address]) -> None:
    """Notify `readers` of a new message."""
    logger.debug("Notifying readers…")
    for reader in readers:
        if not (
            (profile := await fetch_profile(reader)) and (key := profile.encryption_key)
        ):
            logger.warning(
                "Failed notifying %s: Could not fetch profile",
                reader,
            )
            continue

        try:
            address = b64encode(
                crypto.encrypt_anonymous(str(user.address).encode("utf-8"), key)
            )
        except ValueError as error:
            logger.warning(
                "Error notifying %s: Failed to encrypt address: %s",
                reader,
                error,
            )
            continue

        link = model.generate_link(reader, user.address)

        one_notified = False
        for agent in await get_agents(reader):
            if await request(
                _Link(agent, reader, link).notifications,
                auth=True,
                method="PUT",
                data=address,
            ):
                one_notified = True
                logger.debug("Notified %s", reader)

        if one_notified:
            return

        logger.warning("Failed notifying %s", reader)


async def fetch_notifications() -> AsyncGenerator[Notification, None]:
    """Fetch all of `client.user`'s new notifications.

    Note that this generator assumes that you process all notifications yielded by it.
    A subsequent iteration will not yield old notifications that were already processed.
    """
    contents = None
    logger.debug("Fetching notifications…")
    for agent in await get_agents(user.address):
        if not (
            response := await request(
                _Home(agent, user.address).notifications,
                auth=True,
            )
        ):
            continue

        contents = response.read().decode("utf-8")
        break

    if contents:
        notifications_path = data_dir / "notifications.json"

        try:
            with notifications_path.open("r") as file:
                notifications = set(json.load(file))
        except (FileNotFoundError, JSONDecodeError, ValueError):
            notifications = set()

        for notification in contents.split("\n"):
            if not (stripped := notification.strip()):
                continue

            if processed := await _process_notification(stripped, notifications):
                yield processed

        notifications_path.parent.mkdir(parents=True, exist_ok=True)
        with notifications_path.open("w") as file:
            json.dump(tuple(notifications), file)

    logger.debug("Notifications fetched")


async def delete_message(ident: str) -> None:
    """Delete the message with `ident`."""
    logger.debug("Deleting message %s…", ident[:_SHORT])
    for agent in await get_agents(user.address):
        if await request(
            _Message(agent, user.address, ident).message,
            auth=True,
            method="DELETE",
        ):
            logger.info("Deleted message %s", ident[:_SHORT])
            return

    logger.error("Deleting message %s failed", ident[:_SHORT])
    raise WriteError


def save_draft(
    readers: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    reply: str | None = None,
    broadcast: bool = False,
    ident: int | None = None,
) -> None:
    """Serialize and save a message to disk for future use.

    `ident` can be used to update a specific message loaded using `load_drafts()`,
    by default, a new ID is generated.

    See `OutgoingMessage.send()` for other parameters,
    `load_drafts()` on how to retrieve it.
    """
    logger.debug("Saving draft…")
    messages_path = data_dir / "drafts"

    n = (
        ident
        if ident is not None
        else 0
        if not messages_path.is_dir()
        else max(
            *(
                int(path.stem)
                for path in messages_path.iterdir()
                if path.stem.isdigit()
            ),
            0,
        )
        + 1
    )

    message_path = messages_path / f"{n}.json"
    message_path.parent.mkdir(parents=True, exist_ok=True)

    json.dump((readers, subject, body, reply, broadcast), (message_path).open("w"))
    logger.debug("Draft saved as %i.json", n)


def load_drafts() -> Generator[
    tuple[int, str | None, str | None, str | None, str | None, bool], None, None
]:
    """Load all drafts saved to disk.

    See `save_draft()`.
    """
    logger.debug("Loading drafts…")
    if not (messages_path := data_dir / "drafts").is_dir():
        logger.debug("No drafts")
        return

    for path in messages_path.iterdir():
        try:
            message = tuple(json.load(path.open("r")))
            yield (int(path.stem), *message)
        except (JSONDecodeError, ValueError):  # noqa: PERF203
            continue

    logger.debug("Loaded all drafts")


def delete_draft(ident: int) -> None:
    """Delete the draft saved using `ident`.

    See `save_draft()`, `load_drafts()`.
    """
    logger.debug("Deleting draft %i…", ident)

    try:
        (data_dir / "drafts" / f"{ident}.json").unlink()
    except FileNotFoundError as error:
        logger.debug("Failed to delete draft %i: %s", ident, error)
        return

    logger.debug("Deleted draft %i", ident)


def delete_all_saved_messages() -> None:
    """Delete all drafts saved using `save_draft()`."""
    logger.debug("Deleting all drafts…")
    rmtree(data_dir / "drafts", ignore_errors=True)
    logger.debug("Deleted all drafts")


async def delete_account() -> None:
    """Permanently deletes `client.user`'s account."""
    logger.debug("Deleting account…")
    for agent in await get_agents(user.address):
        if await request(
            _Account(agent, user.address).account,
            auth=True,
            method="DELETE",
        ):
            logger.info("Account deleted")
            return

    raise WriteError
    logger.error("Failed to delete account")


async def _process_notification(
    notification: str, notifications: set[str]
) -> Notification | None:
    try:
        ident, link, signing_key_fp, encrypted_notifier = (
            part.strip() for part in notification.split(",", 4)
        )
    except IndexError:
        logger.debug("Invalid notification: %s", notification)
        return None

    if ident in notifications:
        return None

    try:
        notifier = Address(
            crypto.decrypt_anonymous(
                encrypted_notifier,
                user.encryption_keys.private,
            ).decode("utf-8")
        )
    except ValueError:
        logger.debug("Unable to decrypt notification: %s", notification)
        return None

    if not (profile := await fetch_profile(notifier)):
        logger.error(
            "Failed to fetch notification: Could not fetch profile for %s",
            notifier,
        )
        return None

    if signing_key_fp not in {
        crypto.fingerprint(profile.signing_key),
        crypto.fingerprint(profile.last_signing_key)
        if profile.last_signing_key
        else None,
    }:
        logger.debug("Fingerprint mismatch for notification: %s", notification)
        return None

    notifications.add(ident)
    return Notification(
        ident,
        datetime.now(UTC),
        link,
        notifier,
        signing_key_fp,
    )


def _sign_headers(fields: Sequence[str]) -> ...:
    checksum = sha256(("".join(fields)).encode("utf-8"))

    try:
        signature = crypto.sign_data(user.signing_keys.private, checksum.digest())
    except ValueError as error:
        msg = f"Can't sign message: {error}"
        raise ValueError(msg) from error

    return checksum, signature


async def _fetch_envelope(
    url: str,
    ident: str,
    author: Address,
    *,
    broadcast: bool = False,
    exclude: Iterable[str] = (),
) -> tuple[dict[str, str] | None, bool]:
    logger.debug("Fetching envelope %s…", ident[:_SHORT])

    envelopes_dir = data_dir / "envelopes" / author.host_part / author.local_part
    if broadcast:
        envelopes_dir /= "broadcasts"

    envelope_path = envelopes_dir / f"{ident}.json"

    if ident in exclude:
        logger.debug("Removing deleted envelope %s…", ident[:_SHORT])
        envelope_path.unlink(missing_ok=True)
        return None, False

    try:
        headers = dict(json.load(envelope_path.open("r")))

    except (FileNotFoundError, JSONDecodeError, ValueError):
        if not (response := await request(url, auth=not broadcast, method="HEAD")):
            logger.exception("Fetching envelope %s failed", ident[:_SHORT])
            return None, False

        new = True
        headers = dict(response.getheaders())

        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(headers, envelope_path.open("w"))

    else:
        new = False

    logger.debug("Fetched envelope %s", ident[:_SHORT])
    return headers, new


async def _fetch_message_from_agent(
    url: str,
    author: Address,
    ident: str,
    *,
    broadcast: bool = False,
    exclude: Iterable[str] = (),
) -> IncomingMessage | None:
    logger.debug("Fetching message %s…", ident[:_SHORT])

    messages_dir = data_dir / "messages" / author.host_part / author.local_part
    if broadcast:
        messages_dir /= "broadcasts"

    message_path = messages_dir / ident

    if ident in exclude:
        logger.debug("Removing deleted message %s…", ident[:_SHORT])
        message_path.unlink(missing_ok=True)

    envelope, new = await _fetch_envelope(
        url,
        ident,
        author,
        broadcast=broadcast,
        exclude=exclude,
    )
    if not envelope:
        return None

    try:
        message = IncomingMessage(
            ident,
            envelope,
            author,
            user.encryption_keys.private,
            new,
        )
    except ValueError:
        logger.exception("Constructing message %s failed", ident[:_SHORT])
        return None

    if message.is_child:
        message.attachment_url = url

        logger.debug("Fetched message %s", ident[:_SHORT])
        return message

    try:
        contents = message_path.read_bytes()
    except FileNotFoundError:
        if not (response := await request(url, auth=not broadcast)):
            logger.exception(
                "Fetching message %s failed: Failed fetching body",
                ident[:_SHORT],
            )
            return None

        with response:
            contents = response.read()

        message_path.parent.mkdir(parents=True, exist_ok=True)
        message_path.write_bytes(contents)

    if (not message.is_broadcast) and message.access_key:
        try:
            contents = crypto.decrypt_xchacha20poly1305(contents, message.access_key)
        except ValueError:
            logger.exception(
                "Fetching message %s failed: Failed to decrypt body",
                ident[:_SHORT],
            )
            return None

    try:
        message.body = contents.decode("utf-8")
    except UnicodeError:
        logger.exception(
            "Fetching message %s failed: Failed to decode body",
            ident[:_SHORT],
        )
        return None

    logger.debug("Fetched message %s", ident[:_SHORT])
    return message


async def _fetch_message_ids(author: Address, *, broadcasts: bool = False) -> set[str]:
    """Fetch link or broadcast message IDs by `author`, addressed to `client.user`."""
    logger.debug("Fetching message IDs from %s…", author)

    path = data_dir / "envelopes" / author.host_part / author.local_part
    if broadcasts:
        path /= "broadcasts"

    if author == user.address:
        local_ids = set()
    else:
        try:
            local_ids = {p.stem for p in path.iterdir() if p.suffix == ".json"}
        except FileNotFoundError:
            local_ids = set()

    for agent in await get_agents(user.address):
        if not (
            response := await request(
                (
                    _Home(agent, author)
                    if author == user.address
                    else _Mail(agent, author)
                    if broadcasts
                    else _Link(agent, author, model.generate_link(user.address, author))
                ).messages,
                auth=not broadcasts,
            )
        ):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        logger.debug("Fetched message IDs from %s", author)
        return local_ids | {
            stripped for line in contents.split("\n") if (stripped := line.strip())
        }

    logger.warning("Could not fetch message IDs from %s", author)
    return local_ids


async def _fetch_messages(
    author: Address,
    *,
    broadcasts: bool = False,
    exclude: Iterable[str] = (),
) -> tuple[IncomingMessage, ...]:
    messages: dict[str, IncomingMessage] = {}
    for ident in await _fetch_message_ids(author, broadcasts=broadcasts):
        for agent in await get_agents(user.address):
            if message := await _fetch_message_from_agent(
                (
                    _Home(agent, author)
                    if author == user.address
                    else _Mail(agent, author)
                    if broadcasts
                    else _Link(agent, author, model.generate_link(user.address, author))
                ).messages
                + f"/{ident}",
                author,
                ident,
                broadcast=broadcasts,
                exclude=exclude,
            ):
                messages[message.ident] = message
                break

    for ident, message in messages.copy().items():
        if message.parent_id and (parent := messages.get(message.parent_id)):
            parent.add_child(messages.pop(ident))

    for message in messages.values():
        message.reconstruct_from_children()

    logger.debug("Fetched messages from %s", author)
    return tuple(messages.values())


@dataclass(slots=True)
class OutgoingMessage[T: OutgoingMessage]:
    """A local message, to be sent."""

    readers: Iterable[Address]
    subject: str
    content: bytes
    subject_id: str | None = None
    attachments: dict[AttachmentProperties, bytes] = field(default_factory=dict)

    _date: str | None = None
    _attachment: dict[str, str] = field(default_factory=dict)
    _parent_id: str | None = None

    _ident: str = field(default_factory=generate_message_id, init=False)
    _headers: dict[str, str] = field(default_factory=dict, init=False)
    _parts: dict[str, tuple[dict[str, str], bytes]] = field(
        default_factory=dict, init=False
    )

    _built: bool = field(default=False, init=False)

    async def send(self) -> None:
        """Send `self` to `self.readers`."""
        logger.debug("Sending message…")

        try:
            await self._build()

            for agent in await get_agents(user.address):
                if not await request(
                    _Home(agent, user.address).messages,
                    auth=True,
                    headers=self._headers,
                    data=self.content,
                ):
                    logger.error("Failed sending message")
                    raise WriteError

                await notify_readers(self.readers)
                break

            for part in self._parts.values():
                await OutgoingMessage(
                    self.readers,
                    self.subject,
                    part[1],
                    self.subject_id,
                    _attachment=part[0],
                    _parent_id=self._ident,
                    _date=self._date,
                ).send()

        except ValueError as error:
            logger.exception("Error sending message")
            raise WriteError from error

    async def _build(self) -> None:
        if self._built:
            return

        self._date = self._date or datetime.now(UTC).isoformat(timespec="seconds")
        self._headers: dict[str, str] = {
            "Message-Id": self._ident,
            "Content-Type": "application/octet-stream",
        }

        for props, data in self.attachments.items():
            for index, start in enumerate(range(0, len(data), MAX_MESSAGE_SIZE)):
                part = data[start : start + MAX_MESSAGE_SIZE]
                self._parts[props.name] = (
                    {
                        "name": props.name,
                        "id": generate_message_id(),
                        "type": props.type or "application/octet-stream",
                        "size": str(len(data)),
                        "part": f"{index + 1}/{len(self.attachments)}",
                        "modified": props.modified or self._date,
                    },
                    part,
                )

        headers_bytes = "\n".join(
            (
                f"{key}:{value}"
                for key, value in (
                    {
                        "Id": self._headers["Message-Id"],
                        "Author": str(user.address),
                        "Date": self._date,
                        "Size": str(len(self.content)),
                        "Checksum": ";".join(
                            (
                                f"algorithm={crypto.CHECKSUM_ALGORITHM}",
                                f"value={sha256(self.content).hexdigest()}",
                            )
                        ),
                        "Subject": self.subject,
                        "Subject-Id": self.subject_id or self._headers["Message-Id"],
                        "Category": "personal",
                    }
                    | (
                        {"Readers": ",".join(str(reader) for reader in self.readers)}
                        if self.readers
                        else {}
                    )
                    | (
                        {
                            "File": ";".join(
                                f"{key}={value}"
                                for key, value in self._attachment.items()
                            )
                        }
                        if self._attachment
                        else {}
                    )
                    | ({"Parent-Id": self._parent_id} if self._parent_id else {})
                    | (
                        {
                            "Files": ",".join(
                                (
                                    ";".join(
                                        f"{key}={value}" for key, value in a[0].items()
                                    )
                                )
                                for a in self._parts.values()
                            )
                        }
                        if self._parts
                        else {}
                    )
                ).items()
            )
        ).encode("utf-8")

        if self.readers:
            access_key = crypto.random_bytes(32)

            try:
                message_access = await self._build_access(self.readers, access_key)
            except ValueError as error:
                msg = "Error building message: Building access failed"
                raise ValueError(msg) from error

            try:
                self.content = crypto.encrypt_xchacha20poly1305(
                    self.content, access_key
                )
                headers_bytes = crypto.encrypt_xchacha20poly1305(
                    headers_bytes, access_key
                )
            except ValueError as error:
                msg = "Error building message: Encryption failed"
                raise ValueError(msg) from error

            self._headers.update(
                {
                    "Message-Access": ",".join(message_access),
                    "Message-Encryption": f"algorithm={crypto.SYMMETRIC_CIPHER};",
                }
            )

        self._headers["Message-Headers"] = (
            self._headers.get("Message-Headers", "")
            + f"value={b64encode(headers_bytes).decode('utf-8')}"
        )

        checksum_fields = sorted(
            ("Message-Id", "Message-Headers")
            + (("Message-Encryption", "Message-Access") if self.readers else ())
        )

        try:
            checksum, signature = _sign_headers(
                tuple(self._headers[f] for f in checksum_fields)
            )
        except ValueError as error:
            msg = "Error building message: Signing headers failed"
            raise ValueError(msg) from error

        self._headers.update(
            {
                "Content-Length": str(len(self.content)),
                "Message-Checksum": ";".join(
                    (
                        f"algorithm={crypto.CHECKSUM_ALGORITHM}",
                        f"order={':'.join(checksum_fields)}",
                        f"value={checksum.hexdigest()}",
                    )
                ),
                "Message-Signature": ";".join(
                    (
                        f"id={user.encryption_keys.public.key_id or 0}",
                        f"algorithm={crypto.SIGNING_ALGORITHM}",
                        f"value={signature}",
                    )
                ),
            }
        )

        self._built = True

    @staticmethod
    async def _build_access(
        readers: Iterable[Address],
        access_key: bytes,
    ) -> tuple[str, ...]:
        access: list[str] = []
        for reader in (*readers, user.address):
            if not (
                (profile := await fetch_profile(reader))
                and (key := profile.encryption_key)
                and (key_id := key.key_id)
            ):
                msg = "Failed fetching reader profiles"
                raise ValueError(msg)

            try:
                encrypted = crypto.encrypt_anonymous(access_key, key)
            except ValueError as error:
                msg = "Failed to encrypt access key"
                raise ValueError(msg) from error

            access.append(
                ";".join(
                    (
                        f"link={model.generate_link(user.address, reader)}",
                        f"fingerprint={crypto.fingerprint(profile.signing_key)}",
                        f"value={b64encode(encrypted).decode('utf-8')}",
                        f"id={key_id}",
                    )
                )
            )

        return tuple(access)
