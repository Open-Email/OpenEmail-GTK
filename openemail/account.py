# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable
from dataclasses import fields
from shutil import rmtree
from typing import Any

import keyring

from .asyncio import create_task
from .core import client, model
from .core.client import WriteError, user
from .notifier import Notifier
from .store import (
    address_book,
    broadcasts,
    contact_requests,
    inbox,
    outbox,
    profiles,
    secret_service,
    settings,
)


def try_auth(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
):
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth():
        if not await client.try_auth():
            raise ValueError

    def done(success: bool):
        if success:
            if on_success:
                on_success()
            return

        Notifier.send(_("Authentication failed"))

        if on_failure:
            on_failure()

    create_task(auth(), done)


def register(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
):
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth():
        if not await client.register():
            raise ValueError

    def done(success: bool):
        if success:
            if on_success:
                on_success()
            return

        Notifier.send(_("Registration failed, try another address"))

        if on_failure:
            on_failure()

    create_task(auth(), done)


def log_out():
    """Remove the user's local account."""
    for profile in profiles.values():
        profile.set_from_profile(None)

    profiles.clear()
    address_book.clear()
    contact_requests.clear()
    broadcasts.clear()
    inbox.clear()
    outbox.clear()

    settings.reset("address")
    settings.reset("sync-interval")
    settings.reset("empty-trash-interval")
    settings.reset("trusted-domains")
    settings.reset("contact-requests")
    settings.reset("unread-messages")
    settings.reset("trashed-messages")
    settings.reset("deleted-messages")

    keyring.delete_password(secret_service, user.address)

    rmtree(client.data_dir, ignore_errors=True)

    for field in fields(model.User):
        delattr(user, field.name)


async def delete():
    """Permanently delete the user's account."""
    try:
        await client.delete_account()
    except WriteError:
        Notifier.send(_("Failed to delete account"))
        return

    log_out()
