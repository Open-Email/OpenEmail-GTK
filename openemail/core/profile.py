# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from contextlib import suppress
from datetime import UTC, datetime
from logging import getLogger

from . import cache_dir, client, model, urls
from .model import Address, Profile, WriteError

MAX_PROFILE_SIZE = 64_000
MAX_PROFILE_IMAGE_SIZE = 640_000

logger = getLogger(__name__)


async def fetch(address: Address) -> Profile | None:
    """Fetch the remote profile associated with a given `address`."""
    logger.debug("Fetching profile for %s…", address)
    for agent in await client.get_agents(address):
        if not (response := await client.request(urls.Mail(agent, address).profile)):
            continue

        try:
            with response:
                contents = response.read(MAX_PROFILE_SIZE).decode("utf-8")

            profile = Profile(address, contents)

        except (UnicodeError, ValueError):
            continue

        # TODO: Clear cache
        (caches_dir := cache_dir / "profiles").mkdir(parents=True, exist_ok=True)
        (caches_dir / address).write_text(contents)

        logger.debug("Profile fetched for %s", address)
        return profile

    logger.error("Could not fetch profile for %s", address)
    return None


def cached(address: Address) -> Profile | None:
    """Load the locally cached profile of a given `address`, if one exists."""
    with suppress(FileNotFoundError, ValueError):
        return Profile(address, (cache_dir / "profiles" / address).read_text())

    return None


async def update(values: dict[str, str]):
    """Update `core.user`'s public profile with `values`."""
    logger.debug("Updating user profile…")

    values.update({
        "Updated": datetime.now(UTC).isoformat(timespec="seconds"),
        "Encryption-Key": "; ".join((
            f"id={client.user.encryption_keys.public.key_id or 0}",
            f"algorithm={client.user.encryption_keys.public.algorithm}",
            f"value={client.user.encryption_keys.public}",
        )),
        "Signing-Key": "; ".join((
            f"algorithm={client.user.signing_keys.public.algorithm}",
            f"value={client.user.signing_keys.public}",
        )),
    })

    data = (
        f"# Profile of {client.user.address}\n"
        + model.to_fields({k: v for k, v in values.items() if v})
        + "\n#End of profile"
    ).encode("utf-8")

    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Home(agent, client.user.address).profile,
            auth=True,
            method="PUT",
            data=data,
        ):
            logger.info("Profile updated")
            return

    logger.error("Failed to update profile with values %s", values)
    raise WriteError


async def fetch_image(address: Address) -> bytes | None:
    """Fetch the remote profile image associated with a given `address`."""
    logger.debug("Fetching profile image for %s…", address)
    for agent in await client.get_agents(address):
        if not (
            response := await client.request(
                urls.Mail(agent, address).image,
                max_length=MAX_PROFILE_IMAGE_SIZE,
            )
        ):
            continue

        with response:
            contents = response.read()

        # TODO: Clear cache
        (caches_dir := cache_dir / "images").mkdir(parents=True, exist_ok=True)
        (caches_dir / address).write_bytes(contents)

        logger.debug("Profile image fetched for %s", address)
        return contents

    logger.warning("Could not fetch profile image for %s", address)
    return None


def cached_image(address: Address) -> bytes | None:
    """Load the locally cached profile image of a given `address`, if one exists."""
    with suppress(FileNotFoundError, ValueError):
        return (cache_dir / "images" / address).read_bytes()

    return None


async def update_image(image: bytes):
    """Upload `image` to be used as `core.user`'s profile image."""
    logger.debug("Updating profile image…")
    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Home(agent, client.user.address).image,
            auth=True,
            method="PUT",
            data=image,
        ):
            logger.info("Updated profile image.")
            return

    logger.error("Updating profile image failed.")
    raise WriteError


async def delete_image():
    """Delete `core.user`'s profile image."""
    logger.debug("Deleting profile image…")
    for agent in await client.get_agents(client.user.address):
        if await client.request(
            urls.Home(agent, client.user.address).image,
            auth=True,
            method="DELETE",
        ):
            logger.info("Deleted profile image.")
            return

    logger.error("Deleting profile image failed.")
    raise WriteError
