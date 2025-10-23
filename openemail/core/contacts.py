# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from base64 import b64encode
from logging import getLogger

from . import client, crypto, model, urls
from .model import Address, Profile, WriteError

logger = getLogger(__name__)


async def fetch() -> set[tuple[Address, bool]]:
    """Fetch `core.user`'s contacts.

    Returns their addresses and whether broadcasts should be received from them.
    """
    logger.debug("Fetching contact list…")
    addresses = list[tuple[Address, bool]]()

    for agent in await client.get_agents(client.user.address):
        if not (
            response := await client.request(
                urls.Home(agent, client.user.address).links,
                auth=True,
            )
        ):
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
                    client.user.encryption_keys.private,
                ).decode("utf-8")
            except (IndexError, ValueError):
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


async def new(address: Address, *, receive_broadcasts: bool = True) -> Profile:
    """Add `address` to `core.user`'s address book.

    Returns `address`'s profile on success.
    """
    from .profile import fetch

    logger.debug("Adding %s to address book…", address)

    try:
        data = b64encode(
            crypto.encrypt_anonymous(
                model.to_attrs(
                    {
                        "address": address,
                        "broadcasts": "Yes" if receive_broadcasts else "No",
                    }
                ).encode("utf-8"),
                client.user.encryption_keys.public,
            )
        )
    except ValueError:
        logger.exception("Error adding %s to address book: Failed to encrypt", address)
        raise

    if not (profile := await fetch(address)):
        logger.error("Failed adding %s to address book: No profile found")
        raise WriteError

    link = model.generate_link(address, client.user.address)
    for agent in await client.get_agents(address):
        if await client.request(
            urls.Link(agent, client.user.address, link).home,
            auth=True,
            method="PUT",
            data=data,
        ):
            logger.info("Added %s to address book", address)
            return profile

    logger.error("Failed adding %s to address book", address)
    raise WriteError


async def delete(address: Address):
    """Delete `address` from `core.user`'s address book."""
    logger.debug("Deleting contact %s…", address)
    link = model.generate_link(address, client.user.address)
    for agent in await client.get_agents(address):
        if await client.request(
            urls.Link(agent, client.user.address, link).home,
            auth=True,
            method="DELETE",
        ):
            logger.info("Deleted contact %s", address)
            return

    logger.error("Deleting contact %s failed", address)
    raise WriteError
