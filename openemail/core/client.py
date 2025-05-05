# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import asyncio
import json
import logging
from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPResponse, InvalidURL
from json import JSONDecodeError
from os import getenv
from pathlib import Path
from shutil import rmtree
from typing import AsyncGenerator, Generator, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import crypto, model
from .model import Address, Message, Notification, Profile, User

MAX_MESSAGE_SIZE = 64_000_000
MAX_PROFILE_SIZE = 64_000
MAX_PROFILE_IMAGE_SIZE = 640_000

data_dir = Path(getenv("XDG_DATA_DIR", Path.home() / ".local" / "share")) / "openemail"
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
    headers: dict[str, str] = {},
    data: bytes | None = None,
    max_length: int | None = None,
) -> HTTPResponse | None:
    """Make an HTTPS request, handling errors and authentication."""
    headers["User-Agent"] = "Mozilla/5.0"

    try:
        if auth:
            if not (agent := urlparse(url).hostname):
                return None

            headers.update(
                {"Authorization": crypto.get_nonce(agent, user.signing_keys)}
            )

        response = await asyncio.to_thread(
            urlopen, Request(url, method=method, headers=headers, data=data)
        )
    except (InvalidURL, URLError, HTTPError, TimeoutError, ValueError) as error:
        logging.debug(
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
            logging.debug("Content-Length for %s exceeds max_length", url)
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


async def try_auth() -> bool:
    """Try authenticating with `client.user` and return whether the attempt was successful."""
    logging.info("Authenticating…")
    for agent in await get_agents(user.address):
        if await request(_Home(agent, user.address).home, auth=True, method="HEAD"):
            logging.info("Authentication successful")
            return True

    logging.error("Authentication failed")
    return False


async def register() -> bool:
    """Try registering `client.user` and return whether the attempt was successful."""
    logging.info("Registering…")

    data = "\n".join(
        (
            f"Name: {user.address.local_part}",
            f"Encryption-Key: id={user.encryption_keys.public.key_id}; algorithm={crypto.ANONYMOUS_ENCRYPTION_CIPHER}; value={str(user.encryption_keys.public)}",
            f"Signing-Key: algorithm={crypto.SIGNING_ALGORITHM}; value={str(user.signing_keys.public)}",
            f"Updated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        )
    ).encode("utf-8")

    for agent in await get_agents(user.address):
        if await request(_Account(agent, user.address).account, auth=True, data=data):
            logging.info("Authentication successful")
            return True

    # TODO: More descriptive errors
    logging.error("Registration failed")
    return False


async def fetch_profile(address: Address) -> Profile | None:
    """Fetch the remote profile associated with a given `address`."""
    logging.debug("Fetching profile for %s…", address)
    for agent in await get_agents(address):
        if not (response := await request(_Mail(agent, address).profile)):
            continue

        with response:
            try:
                logging.debug("Profile fetched for %s", address)
                return Profile(address, response.read(MAX_PROFILE_SIZE).decode("utf-8"))
            except UnicodeError:
                continue

            break

    logging.error("Could not fetch profile for %s", address)
    return None


async def update_profile(values: dict[str, str]) -> None:
    """Update `client.user`'s public profile with `values`."""
    logging.debug("Updating user profile…")

    values.update(
        {
            "Updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
        + "\n".join((": ".join((k.title(), v))) for k, v in values.items() if v)
        + "\n##End of profile"
    ).encode("utf-8")

    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).profile,
            auth=True,
            method="PUT",
            data=data,
        ):
            logging.info("Profile updated")
            return

    logging.error("Failed to update profile with values %s", values)
    raise WriteError


async def fetch_profile_image(address: Address) -> bytes | None:
    """Fetch the remote profile image associated with a given `address`."""
    logging.debug("Fetching profile image for %s…", address)
    for agent in await get_agents(address):
        if not (
            response := await request(
                _Mail(agent, address).image,
                max_length=MAX_PROFILE_IMAGE_SIZE,
            )
        ):
            continue

        with response:
            logging.debug("Profile image fetched for %s", address)
            return response.read()
            break

    logging.warning("Could not fetch profile image for %s", address)
    return None


async def update_profile_image(image: bytes) -> None:
    """Upload `image` to be used as `client.user`'s profile image."""
    logging.debug("Updating profile image…")
    for agent in await get_agents(user.address):
        if await request(
            _Home(agent, user.address).image,
            auth=True,
            method="PUT",
            data=image,
        ):
            logging.info("Updated profile image.")
            return

    logging.error("Updating profile image failed.")
    raise WriteError


async def delete_profile_image() -> None:
    """Delete `client.user`'s profile image."""
    logging.debug("Deleting profile image…")
    for agent in await get_agents(user.address):
        if await request(_Home(agent, user.address).image, auth=True, method="DELETE"):
            logging.info("Deleted profile image.")
            return

    logging.error("Deleting profile image failed.")
    raise WriteError


async def fetch_contacts() -> set[Address]:
    """Fetch `client.user`'s contact list."""
    logging.debug("Fetching contact list…")
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
            if len(parts := line.strip().split(",")) != 2:
                continue

            try:
                contact = crypto.decrypt_anonymous(
                    parts[1].strip(),
                    user.encryption_keys.private,
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
                addresses.append(Address(model.parse_headers(contact)["address"]))
            except KeyError:
                continue

        break

    logging.debug("Contact list fetched")
    return set(addresses)


async def new_contact(address: Address) -> None:
    """Add `address` to `client.user`'s address book."""
    logging.debug("Adding %s to address book…", address)

    try:
        data = b64encode(
            crypto.encrypt_anonymous(
                f"address={address};broadcasts=yes".encode("utf-8"),
                user.encryption_keys.public,
            )
        )
    except ValueError as error:
        logging.error(
            "Error adding %s to address book: Failed to encrypt address: %s",
            address,
            error,
        )
        raise WriteError

    link = model.generate_link(address, user.address)
    for agent in await get_agents(address):
        if await request(
            _Link(agent, user.address, link).home,
            auth=True,
            method="PUT",
            data=data,
        ):
            logging.info("Added %s to address book", address)
            return

    logging.error("Failed adding %s to address book", address)
    raise WriteError


async def delete_contact(address: Address) -> None:
    """Delete `address` from `client.user`'s address book."""
    logging.debug("Deleting contact %s…", address)
    link = model.generate_link(address, user.address)
    for agent in await get_agents(address):
        if await request(
            _Link(agent, user.address, link).home,
            auth=True,
            method="DELETE",
        ):
            logging.info("Deleted contact %s", address)
            return

    logging.error("Deleting contact %s failed", address)
    raise WriteError


async def fetch_broadcasts(
    author: Address, *, exclude: Iterable[str] = ()
) -> tuple[Message, ...]:
    """Fetch broadcasts by `author`, without messages with IDs in `exclude`."""
    logging.debug("Fetching broadcasts from %s…", author)
    return await _fetch_messages(author, broadcasts=True, exclude=exclude)


async def fetch_link_messages(
    author: Address, *, exclude: Iterable[str] = ()
) -> tuple[Message, ...]:
    """Fetch messages by `author`, addressed to `client.user`, without messages with IDs in `exclude`."""
    logging.debug("Fetching link messages messages from %s…", author)
    return await _fetch_messages(author, exclude=exclude)


async def download_attachment(parts: Iterable[Message]) -> bytes | None:
    """Download and reconstruct an attachment from `parts`."""
    data = b""
    for part in parts:
        if not (
            part.attachment_url
            and (response := await request(part.attachment_url, auth=True))
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


async def send_message(
    readers: Iterable[Address],
    subject: str,
    body: str,
    subject_id: str | None = None,
    attachments: dict[str, bytes] = {},
) -> None:
    """Send a message to `readers`.

    If `readers` is empty, send a broadcast.

    `subject_id` is an optional ID of a thread that the message should be part of.
    """
    logging.debug("Sending message…")
    if not body:
        logging.warning("Failed sending message: Empty body")
        raise WriteError

    messages: list[tuple[dict[str, str], bytes]] = []
    date = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        ident, headers, content, parts = await _build_message(
            readers,
            subject,
            body.encode("utf-8"),
            subject_id,
            date=date,
            attachments=attachments,
        )
        messages.append((headers, content))

        for part in parts.values():
            fields, data = part
            _id, h, c, _p = await _build_message(
                readers,
                subject,
                data,
                subject_id,
                attachment=fields,
                parent_id=ident,
                date=date,
            )
            messages.append((h, c))

    except WriteError as error:
        logging.error("Error sending message: %s", error)
        raise error

    sent = 0
    for message in messages:
        for agent in await get_agents(user.address):
            if await request(
                _Home(agent, user.address).messages,
                auth=True,
                headers=message[0],
                data=message[1],
            ):
                await notify_readers(readers)
                sent += 1
                break

    if sent >= len(messages):
        logging.info("Message sent successfully")
        return

    logging.error("Failed sending message")
    raise WriteError


async def notify_readers(readers: Iterable[Address]) -> None:
    """Notify `readers` of a new message."""
    logging.debug("Notifying readers…")
    for reader in readers:
        if not (
            (profile := await fetch_profile(reader)) and (key := profile.encryption_key)
        ):
            logging.warning(
                "Failed notifying %s: Could not fetch profile",
                reader,
            )
            continue

        try:
            address = b64encode(
                crypto.encrypt_anonymous(str(user.address).encode("utf-8"), key)
            )
        except ValueError as error:
            logging.warning(
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
                logging.debug("Notified %s", reader)
                one_notified = True
        if not one_notified:
            logging.warning("Failed notifying %s", reader)


async def fetch_notifications() -> AsyncGenerator[Notification, None]:
    """Fetch all of `client.user`'s new notifications.

    Note that this generator assumes that you process all notifications yielded by it
    and that a subsequent iteration will not yield "old" notifications that were already processed.
    """
    contents = None
    logging.debug("Fetching notifications…")
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

            try:
                ident, link, signing_key_fp, encrypted_notifier = (
                    part.strip() for part in stripped.split(",", 4)
                )
            except IndexError:
                logging.debug("Invalid notification: %s", notification)
                continue

            if ident in notifications:
                continue

            try:
                notifier = Address(
                    crypto.decrypt_anonymous(
                        encrypted_notifier,
                        user.encryption_keys.private,
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

            if signing_key_fp not in {
                crypto.fingerprint(profile.signing_key),
                crypto.fingerprint(profile.last_signing_key) if profile.last_signing_key else None,
            }:
                logging.debug("Fingerprint mismatch for notification: %s", notification)
                continue

            yield Notification(
                ident,
                datetime.now(timezone.utc),
                link,
                notifier,
                signing_key_fp,
            )
            notifications.add(ident)
        if not notifications_path.parent.exists():
            notifications_path.parent.mkdir(parents=True, exist_ok=True)
        with notifications_path.open("w") as file:
            json.dump(tuple(notifications), file)

    logging.debug("Notifications fetched")


async def delete_message(ident: str) -> None:
    """Delete the message with `ident`."""
    logging.debug("Deleting message %s…", ident[:8])
    for agent in await get_agents(user.address):
        if await request(
            _Message(agent, user.address, ident).message,
            auth=True,
            method="DELETE",
        ):
            logging.info("Deleted message %s", ident[:8])
            return

    logging.error("Deleting message %s failed", ident[:8])
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

    See `send_message()` for other parameters, `load_drafts()` on how to retrieve it.
    """
    logging.debug("Saving draft…")
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
    logging.debug("Draft saved as %i.json", n)


def load_drafts() -> Generator[
    tuple[int, str | None, str | None, str | None, str | None, bool], None, None
]:
    """Load all drafts saved to disk.

    See `save_draft()`.
    """
    logging.debug("Loading drafts…")
    if not (messages_path := data_dir / "drafts").is_dir():
        logging.debug("No drafts")
        return

    for path in messages_path.iterdir():
        try:
            message = tuple(json.load(path.open("r")))
            yield (int(path.stem),) + message
        except (JSONDecodeError, ValueError):
            continue

    logging.debug("Loaded all drafts")


def delete_draft(ident: int) -> None:
    """Delete the draft saved using `ident`.

    See `save_draft()`, `load_drafts()`.
    """
    logging.debug("Deleting draft %i…", ident)

    try:
        (data_dir / "drafts" / f"{ident}.json").unlink()
    except FileNotFoundError as error:
        logging.debug("Failed to delete draft %i: %s", ident, error)
        return

    logging.debug("Deleted draft %i", ident)


def delete_all_saved_messages() -> None:
    """Delete all drafts saved using `save_draft()`."""
    logging.debug("Deleting all drafts…")
    rmtree(data_dir / "drafts", ignore_errors=True)
    logging.debug("Deleted all drafts")


async def delete_account() -> None:
    """Permanently deletes `client.user`'s account."""
    logging.debug("Deleting account…")
    for agent in await get_agents(user.address):
        if await request(
            _Account(agent, user.address).account,
            auth=True,
            method="DELETE",
        ):
            logging.info("Account deleted")
            return

    raise WriteError
    logging.error("Failed to delete account")


def _sign_headers(fields: Sequence[str]) -> ...:
    checksum = sha256(("".join(fields)).encode("utf-8"))

    try:
        signature = crypto.sign_data(user.signing_keys.private, checksum.digest())
    except ValueError as error:
        raise ValueError(f"Can't sign message: {error}")

    return checksum, signature


async def _fetch_envelope(
    url: str,
    ident: str,
    author: Address,
    *,
    broadcast: bool = False,
) -> tuple[dict[str, str] | None, bool]:
    logging.debug("Fetching envelope %s…", ident[:8])

    envelopes_dir = data_dir / "envelopes" / author.host_part / author.local_part
    if broadcast:
        envelopes_dir /= "broadcasts"

    envelope_path = envelopes_dir / f"{ident}.json"

    try:
        headers = dict(json.load(envelope_path.open("r")))

    except (FileNotFoundError, JSONDecodeError, ValueError):
        if not (response := await request(url, auth=True, method="HEAD")):
            logging.error("Fetching envelope %s failed", ident[:8])
            return None, False

        new = True
        headers = dict(response.getheaders())

        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(headers, envelope_path.open("w"))

    else:
        new = False

    logging.debug("Fetched envelope %s", ident[:8])
    return headers, new


async def _fetch_message_from_agent(
    url: str,
    author: Address,
    ident: str,
    broadcast: bool = False,
) -> Message | None:
    logging.debug("Fetching message %s…", ident[:8])

    envelope, new = await _fetch_envelope(url, ident, author, broadcast=broadcast)
    if not envelope:
        return None

    try:
        message = Message(ident, envelope, author, user.encryption_keys.private, new)
    except ValueError as error:
        logging.error("Constructing message %s failed: %s", ident[:8], error)
        return None

    if message.is_child:
        message.attachment_url = url

        logging.debug("Fetched message %s", ident[:8])
        return message

    messages_dir = data_dir / "messages" / author.host_part / author.local_part
    if broadcast:
        messages_dir /= "broadcasts"

    message_path = messages_dir / ident

    try:
        contents = message_path.read_bytes()
    except FileNotFoundError:
        if not (response := await request(url, auth=True)):
            logging.error(
                "Fetching message %s failed: Failed fetching body",
                ident[:8],
            )
            return None

        with response:
            contents = response.read()

        message_path.parent.mkdir(parents=True, exist_ok=True)
        message_path.write_bytes(contents)

    if (not message.is_broadcast) and message.access_key:
        try:
            contents = crypto.decrypt_xchacha20poly1305(contents, message.access_key)
        except ValueError as error:
            logging.error(
                "Fetching message %s failed: Failed to decrypt body: %s",
                ident[:8],
                error,
            )
            return None

    try:
        message.body = contents.decode("utf-8")

        logging.debug("Fetched message %s", ident[:8])
        return message

    except UnicodeError as error:
        logging.error(
            "Fetching message %s failed: Failed to decode body: %s",
            ident[:8],
            error,
        )
        return None


async def _fetch_message_ids(author: Address, broadcasts: bool = False) -> set[str]:
    """Fetch link or broadcast message IDs by `author`, addressed to `client.user`."""
    logging.debug("Fetching message IDs from %s…", author)

    envelopes_dir = data_dir / "envelopes" / author.host_part / author.local_part
    if broadcasts:
        envelopes_dir /= "broadcasts"

    if author == user.address:
        local_ids = set()
    else:
        try:
            children = envelopes_dir.iterdir()
        except FileNotFoundError:
            children = ()

        local_ids = {path.stem for path in children if path.suffix == ".json"}

    for agent in await get_agents(user.address):
        if not (
            response := await request(
                (
                    _Mail(agent, author)
                    if broadcasts
                    else _Link(agent, author, model.generate_link(user.address, author))
                ).messages,
                auth=True,
            )
        ):
            continue

        with response:
            try:
                contents = response.read().decode("utf-8")
            except UnicodeError:
                continue

        logging.debug("Fetched message IDs from %s", author)
        return local_ids | {
            stripped for line in contents.split("\n") if (stripped := line.strip())
        }

    logging.warning("Could not fetch message IDs from %s", author)
    return local_ids


async def _fetch_messages(
    author: Address,
    *,
    broadcasts: bool = False,
    exclude: Iterable[str] = (),
) -> tuple[Message, ...]:
    messages: dict[str, Message] = {}
    for ident in await _fetch_message_ids(author, broadcasts=broadcasts):
        if ident in exclude:
            continue

        for agent in await get_agents(user.address):
            if message := await _fetch_message_from_agent(
                (
                    _Mail(agent, author)
                    if broadcasts
                    else _Link(agent, author, model.generate_link(user.address, author))
                ).messages
                + f"/{ident}",
                author,
                ident,
                broadcast=broadcasts,
            ):
                messages[message.ident] = message
                break

    for ident, message in messages.copy().items():
        if message.parent_id:
            if parent := messages.get(message.parent_id):
                parent.add_child(messages.pop(ident))

    for message in messages.values():
        message.reconstruct_from_children()

    logging.debug("Fetched messages from %s", author)
    return tuple(messages.values())


async def _build_message_access(
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
            raise ValueError("Failed fetching reader profiles")

        try:
            encrypted = crypto.encrypt_anonymous(access_key, key)
        except ValueError as error:
            raise ValueError("Failed to encrypt access key") from error

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


async def _build_message(
    readers: Iterable[Address],
    subject: str,
    content: bytes,
    subject_id: str | None = None,
    *,
    attachment: dict[str, str] = {},
    parent_id: str | None = None,
    date: str | None = None,
    attachments: dict[str, bytes] = {},
) -> tuple[str, dict[str, str], bytes, dict[str, tuple[dict[str, str], bytes]]]:
    date = date or datetime.now(timezone.utc).isoformat(timespec="seconds")
    headers: dict[str, str] = {
        "Message-Id": generate_message_id(),
        "Content-Type": "application/octet-stream",
    }

    files = {}
    modified = date  # TODO
    for name, data in attachments.items():
        for index, start in enumerate(range(0, len(data), MAX_MESSAGE_SIZE)):
            part = data[start : start + MAX_MESSAGE_SIZE]
            files[name] = (
                {
                    "name": name,
                    "id": generate_message_id(),
                    "type": "application/octet-stream",  # TODO
                    "size": str(len(data)),
                    "part": f"{index + 1}/{len(attachments)}",
                    "modified": modified,
                },
                part,
            )

    headers_bytes = "\n".join(
        (
            ":".join((key, value))
            for key, value in (
                {
                    "Id": headers["Message-Id"],
                    "Author": str(user.address),
                    "Date": date,
                    "Size": str(len(content)),
                    "Checksum": ";".join(
                        (
                            f"algorithm={crypto.CHECKSUM_ALGORITHM}",
                            f"value={sha256(content).hexdigest()}",
                        )
                    ),
                    "Subject": subject,
                    "Subject-Id": subject_id or headers["Message-Id"],
                    "Category": "personal",
                }
                | (
                    {"Readers": ",".join((str(reader) for reader in readers))}
                    if readers
                    else {}
                )
                | (
                    {
                        "File": ";".join(
                            f"{key}={value}" for key, value in attachment.items()
                        )
                    }
                    if attachment
                    else {}
                )
                | ({"Parent-Id": parent_id} if parent_id else {})
                | (
                    {
                        "Files": ",".join(
                            (";".join(f"{key}={value}" for key, value in a[0].items()))
                            for a in files.values()
                        )
                    }
                    if files
                    else {}
                )
            ).items()
        )
    ).encode("utf-8")

    if readers:
        access_key = crypto.random_bytes(32)

        try:
            message_access = await _build_message_access(readers, access_key)
        except ValueError as error:
            raise WriteError from error

        try:
            content = crypto.encrypt_xchacha20poly1305(content, access_key)
            headers_bytes = crypto.encrypt_xchacha20poly1305(headers_bytes, access_key)
        except ValueError as error:
            raise WriteError from error

        headers.update(
            {
                "Message-Access": ",".join(message_access),
                "Message-Encryption": f"algorithm={crypto.SYMMETRIC_CIPHER};",
            }
        )

    headers["Message-Headers"] = (
        headers.get("Message-Headers", "")
        + f"value={b64encode(headers_bytes).decode('utf-8')}"
    )

    checksum_fields = sorted(
        ("Message-Id", "Message-Headers")
        + (("Message-Encryption", "Message-Access") if readers else ())
    )

    try:
        checksum, signature = _sign_headers(tuple(headers[f] for f in checksum_fields))
    except ValueError as error:
        raise WriteError from error

    headers.update(
        {
            "Content-Length": str(len(content)),
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

    return headers["Message-Id"], headers, content, files
