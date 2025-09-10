# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from datetime import UTC, datetime
from logging import getLogger

from . import client, crypto, model, urls
from .model import WriteError

logger = getLogger(__name__)


async def try_auth() -> bool:
    """Try authenticating with `core.user`.

    Returns whether the attempt was successful.
    """
    logger.info("Authenticating…")
    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Home(agent, client.user.address).home, auth=True, method="HEAD"
        ):
            logger.info("Authentication successful")
            return True

    logger.error("Authentication failed")
    return False


async def register() -> bool:
    """Try registering `core.user` and return whether the attempt was successful."""
    logger.info("Registering…")

    data = model.to_fields(
        {
            "Name": client.user.address.local_part,
            "Encryption-Key": model.to_attrs(
                {
                    "id": client.user.encryption_keys.public.key_id,
                    "algorithm": crypto.ANONYMOUS_ENCRYPTION_CIPHER,
                    "value": client.user.encryption_keys.public,
                }
            ),
            "Signing-Key": model.to_attrs(
                {
                    "algorithm": crypto.SIGNING_ALGORITHM,
                    "value": client.user.signing_keys.public,
                }
            ),
            "Updated": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    ).encode("utf-8")

    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Account(agent, client.user.address).account, auth=True, data=data
        ):
            logger.info("Authentication successful")
            return True

    # TODO: More descriptive errors
    logger.error("Registration failed")
    return False


async def delete():
    """Permanently deletes `core.user`'s account."""
    logger.debug("Deleting account…")
    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Account(agent, client.user.address).account,
            auth=True,
            method="DELETE",
        ):
            logger.info("Account deleted")
            return

    raise WriteError
    logger.error("Failed to delete account")
