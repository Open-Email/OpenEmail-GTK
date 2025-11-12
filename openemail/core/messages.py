# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import json
from base64 import b64encode
from collections.abc import AsyncGenerator, Iterable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from itertools import chain
from json import JSONDecodeError
from logging import getLogger
from pathlib import Path

from . import client, crypto, data_dir, model, urls
from .model import (
    Address,
    IncomingMessage,
    Message,
    Notification,
    OutgoingMessage,
    WriteError,
)

_SHORT = 8

logger = getLogger(__name__)


async def fetch_broadcasts(
    author: Address, *, exclude: Iterable[str] = ()
) -> tuple[IncomingMessage, ...]:
    """Fetch broadcasts by `author`, without messages with IDs in `exclude`."""
    logger.debug("Fetching broadcasts from %s…", author)
    return await _fetch(author, broadcasts=True, exclude=exclude)


async def fetch_link_messages(
    author: Address, *, exclude: Iterable[str] = ()
) -> tuple[IncomingMessage, ...]:
    """Fetch messages by `author`, addressed to `core.user`.

    `exclude` are Message-Ids to ignore.
    """
    logger.debug("Fetching link messages messages from %s…", author)
    return await _fetch(author, exclude=exclude)


async def fetch_outbox() -> tuple[IncomingMessage, ...]:
    """Fetch messages by `core.user` that are currently available to be retrieved."""
    logger.debug("Fetching outbox…")
    return await _fetch(client.user.address, remote_only=True)


async def fetch_sent(exclude: Iterable[str] = ()) -> tuple[IncomingMessage, ...]:
    """Fetch messages sent by `core.user`."""
    logger.debug("Fetching sent messages…")
    return await _fetch(client.user.address, exclude=exclude)


async def download_attachment(parts: Iterable[Message]) -> bytes | None:
    """Download and reconstruct an attachment from `parts`."""
    data = b""
    for part in parts:
        if not (
            part.attachment_url
            and (
                response := await client.request(
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


async def notify_readers(readers: Iterable[Address]):
    """Notify `readers` of a new message."""
    from .profile import fetch

    logger.debug("Notifying readers…")
    for reader in readers:
        if not ((profile := await fetch(reader)) and (key := profile.encryption_key)):
            logger.warning(
                "Failed notifying %s: Could not fetch profile",
                reader,
            )
            continue

        try:
            address = b64encode(
                crypto.encrypt_anonymous(client.user.address.encode("utf-8"), key)
            )
        except ValueError as error:
            logger.warning(
                "Error notifying %s: Failed to encrypt address: %s",
                reader,
                error,
            )
            continue

        link = model.generate_link(reader, client.user.address)

        one_notified = False
        for agent in await client.get_agents(reader):
            if await client.request(
                urls.Link(agent, reader, link).notifications,
                auth=True,
                method="PUT",
                data=address,
            ):
                one_notified = True
                logger.debug("Notified %s", reader)

        if one_notified:
            return

        logger.warning("Failed notifying %s", reader)


async def fetch_notifications() -> AsyncGenerator[Notification]:
    """Fetch all of `core.user`'s new notifications.

    Note that this generator assumes that you process all notifications yielded by it.
    A subsequent iteration will not yield old notifications that were already processed.
    """
    contents = None
    logger.debug("Fetching notifications…")
    for agent in await client.get_agents(client.user.address):
        if not (
            response := await client.request(
                urls.Home(agent, client.user.address).notifications,
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
            notifications = set[str]()

        for notification in contents.split("\n"):
            if not (stripped := notification.strip()):
                continue

            if processed := await _process_notification(stripped, notifications):
                yield processed

        notifications_path.parent.mkdir(parents=True, exist_ok=True)
        with notifications_path.open("w") as file:
            json.dump(tuple(notifications), file)

    logger.debug("Notifications fetched")


async def send(msg: OutgoingMessage, /):
    """Send `msg` to `msg.readers`."""
    logger.debug("Sending message…")
    msg.sending = True

    try:
        await _build(msg)

        for agent in await client.get_agents(client.user.address):
            if not await client.request(
                urls.Home(agent, client.user.address).messages,
                auth=True,
                headers=msg.headers,
                data=msg.content,
            ):
                logger.error("Failed sending message")
                msg.sending = False
                raise WriteError

            await notify_readers(msg.readers)
            break

        for part in chain.from_iterable(msg.attachments.values()):
            await send(part)

    except ValueError as error:
        logger.exception("Error sending message")
        msg.sending = False
        raise WriteError from error

    msg.sending = False


async def delete(ident: str):
    """Delete the message with `ident`.

    Note that this will not delete children of the message,
    nor will it remove the message from disk. For that, see remove_from_disk().
    """
    logger.debug("Deleting message %s…", ident[:_SHORT])
    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Message(agent, client.user.address, ident).message,
            auth=True,
            method="DELETE",
        ):
            logger.info("Deleted message %s", ident[:_SHORT])
            return

    logger.error("Deleting message %s failed", ident[:_SHORT])
    raise WriteError


def remove_from_disk(msg: Message, /):
    """Remove `msg` from disk if it has been downloaded before.

    Note that this will not remove children of `msg`.
    """
    logger.debug("Removing message %s from disk…", msg.ident[:_SHORT])
    host, local = msg.author.host_part, msg.author.local_part
    path = Path(host, local, "broadcasts" if msg.is_broadcast else "")

    (data_dir / "envelopes" / path / f"{msg.ident}.json").unlink(missing_ok=True)
    (data_dir / "messages" / path / msg.ident).unlink(True)
    logger.debug("Removed message %s from disk", msg.ident[:_SHORT])


async def _process_notification(
    notification: str, notifications: set[str]
) -> Notification | None:
    from .profile import fetch

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
                client.user.encryption_keys.private,
            ).decode("utf-8")
        )
    except ValueError:
        logger.debug("Unable to decrypt notification: %s", notification)
        return None

    if not (profile := await fetch(notifier)):
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
        with envelope_path.open("r") as file:
            headers = dict(json.load(file))

    except (FileNotFoundError, JSONDecodeError, ValueError):
        if not (
            response := await client.request(
                url,
                auth=not broadcast,
                method="HEAD",
            )
        ):
            logger.exception("Fetching envelope %s failed", ident[:_SHORT])
            return None, False

        new = True
        headers = dict(response.getheaders())

        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        with envelope_path.open("w") as file:
            json.dump(headers, file)

    else:
        new = False

    logger.debug("Fetched envelope %s", ident[:_SHORT])
    return headers, new


async def _fetch_from_agent(
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
        msg = IncomingMessage(
            ident, author, envelope, client.user.encryption_keys.private, new=new
        )
    except ValueError:
        logger.exception("Constructing message %s failed", ident[:_SHORT])
        return None

    if msg.is_child:
        msg.attachment_url = url

        logger.debug("Fetched message %s", ident[:_SHORT])
        return msg

    try:
        contents = message_path.read_bytes()
    except FileNotFoundError:
        if not (response := await client.request(url, auth=not broadcast)):
            logger.exception(
                "Fetching message %s failed: Failed fetching body",
                ident[:_SHORT],
            )
            return None

        with response:
            contents = response.read()

        message_path.parent.mkdir(parents=True, exist_ok=True)
        message_path.write_bytes(contents)

    if (not msg.is_broadcast) and msg.access_key:
        try:
            contents = crypto.decrypt_xchacha20poly1305(contents, msg.access_key)
        except ValueError:
            logger.exception(
                "Fetching message %s failed: Failed to decrypt body",
                ident[:_SHORT],
            )
            return None

    try:
        msg.body = contents.decode("utf-8")
    except UnicodeError:
        logger.exception(
            "Fetching message %s failed: Failed to decode body",
            ident[:_SHORT],
        )
        return None

    logger.debug("Fetched message %s", ident[:_SHORT])
    return msg


async def _fetch_idents(
    author: Address, *, broadcasts: bool = False
) -> tuple[set[str], set[str]]:
    """Fetch link or broadcast message IDs by `author`, addressed to `core.user`.

    Returns a touple of two sets: local and remote IDs.
    """
    logger.debug("Fetching message IDs from %s…", author)

    path = data_dir / "envelopes" / author.host_part / author.local_part
    if broadcasts:
        path /= "broadcasts"

    try:
        local_ids = {p.stem for p in path.iterdir() if p.suffix == ".json"}
    except FileNotFoundError:
        local_ids = set[str]()

    for agent in await client.get_agents(client.user.address):
        if not (
            response := await client.request(
                (
                    urls.Home(agent, author)
                    if author == client.user.address
                    else urls.Mail(agent, author)
                    if broadcasts
                    else urls.Link(
                        agent, author, model.generate_link(client.user.address, author)
                    )
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
        return local_ids, {
            stripped for line in contents.split("\n") if (stripped := line.strip())
        }

    logger.warning("Could not fetch message IDs from %s", author)
    return local_ids, set()


async def _fetch(
    author: Address,
    *,
    broadcasts: bool = False,
    remote_only: bool = False,
    exclude: Iterable[str] = (),
) -> tuple[IncomingMessage, ...]:
    messages = dict[str, IncomingMessage]()
    local, remote = await _fetch_idents(author, broadcasts=broadcasts)
    for ident in remote if remote_only else local | remote:
        for agent in await client.get_agents(client.user.address):
            if msg := await _fetch_from_agent(
                (
                    urls.Home(agent, author)
                    if author == client.user.address
                    else urls.Mail(agent, author)
                    if broadcasts
                    else urls.Link(
                        agent, author, model.generate_link(client.user.address, author)
                    )
                ).messages
                + f"/{ident}",
                author,
                ident,
                broadcast=broadcasts,
                exclude=exclude,
            ):
                messages[msg.ident] = msg
                break

    for ident, msg in messages.copy().items():
        if msg.parent_id and (parent := messages.get(msg.parent_id)):
            parent.add_child(messages.pop(ident))

    for msg in messages.values():
        msg.reconstruct_from_children()

    logger.debug("Fetched messages from %s", author)
    return tuple(messages.values())


async def _build(msg: OutgoingMessage, /):
    if msg.headers:
        return

    msg.headers = {
        "Message-Id": msg.ident,
        "Content-Type": "application/octet-stream",
    }

    headers_bytes = model.to_fields(
        {
            "Id": msg.headers["Message-Id"],
            "Author": client.user.address,
            "Date": msg.date.isoformat(timespec="seconds"),
            "Size": str(len(msg.content)),
            "Checksum": model.to_attrs(
                {
                    "algorithm": crypto.CHECKSUM_ALGORITHM,
                    "value": sha256(msg.content).hexdigest(),
                }
            ),
            "Subject": msg.subject,
            "Subject-Id": msg.subject_id,
            "Category": "personal",
        }
        | ({"Readers": ",".join(map(str, msg.readers))} if msg.readers else {})
        | ({"File": model.to_attrs(msg.file.dict)} if msg.file else {})
        | ({"Parent-Id": msg.parent_id} if msg.parent_id else {})
        | (
            {"Files": ",".join((model.to_attrs(a.dict)) for a in msg.files)}
            if msg.files
            else {}
        )
    ).encode("utf-8")

    if msg.readers:
        msg.access_key = crypto.random_bytes(32)

        try:
            access = await _build_access(msg.readers, msg.access_key)
        except ValueError as error:
            e = "Error building message: Building access failed"
            raise ValueError(e) from error

        try:
            msg.content = crypto.encrypt_xchacha20poly1305(msg.content, msg.access_key)
            headers_bytes = crypto.encrypt_xchacha20poly1305(
                headers_bytes, msg.access_key
            )
        except ValueError as error:
            e = "Error building message: Encryption failed"
            raise ValueError(e) from error

        msg.headers.update(
            {
                "Message-Access": ",".join(access),
                "Message-Encryption": f"algorithm={crypto.SYMMETRIC_CIPHER};",
            }
        )

    msg.headers["Message-Headers"] = (
        msg.headers.get("Message-Headers", "")
        + f"value={b64encode(headers_bytes).decode('utf-8')}"
    )

    checksum_fields = sorted(
        ("Message-Id", "Message-Headers")
        + (("Message-Encryption", "Message-Access") if msg.readers else ())
    )

    try:
        checksum, signature = _sign_headers(
            tuple(msg.headers[f] for f in checksum_fields)
        )
    except ValueError as error:
        e = "Error building message: Signing headers failed"
        raise ValueError(e) from error

    msg.headers.update(
        {
            "Content-Length": str(len(msg.content)),
            "Message-Checksum": model.to_attrs(
                {
                    "algorithm": crypto.CHECKSUM_ALGORITHM,
                    "order": ":".join(checksum_fields),
                    "value": checksum.hexdigest(),
                }
            ),
            "Message-Signature": model.to_attrs(
                {
                    "id": client.user.encryption_keys.public.key_id or 0,
                    "algorithm": crypto.SIGNING_ALGORITHM,
                    "value": signature,
                }
            ),
        }
    )


async def _build_access(
    readers: Iterable[Address],
    access_key: bytes,
) -> tuple[str, ...]:
    from .profile import fetch

    access = list[str]()
    for reader in *readers, client.user.address:
        if not (
            (profile := await fetch(reader))
            and (key := profile.encryption_key)
            and (key_id := key.key_id)
        ):
            e = "Failed fetching reader profiles"
            raise ValueError(e)

        try:
            encrypted = crypto.encrypt_anonymous(access_key, key)
        except ValueError as error:
            e = "Failed to encrypt access key"
            raise ValueError(e) from error

        access.append(
            model.to_attrs(
                {
                    "link": model.generate_link(client.user.address, reader),
                    "fingerprint": crypto.fingerprint(profile.signing_key),
                    "value": b64encode(encrypted).decode("utf-8"),
                    "id": key_id,
                }
            )
        )

    return tuple(access)


def _sign_headers(fields: Sequence[str]) -> ...:
    checksum = sha256(("".join(fields)).encode("utf-8"))

    try:
        signature = crypto.sign_data(
            client.user.signing_keys.private, checksum.digest()
        )
    except ValueError as error:
        e = f"Can't sign message: {error}"
        raise ValueError(e) from error

    return checksum, signature
