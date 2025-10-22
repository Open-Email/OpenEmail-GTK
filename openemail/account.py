# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from collections.abc import Callable
from dataclasses import fields
from shutil import rmtree
from typing import Any

import keyring

from . import Notifier, core, store, tasks
from .core import account, client, model
from .core.model import WriteError


def try_auth(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
):
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth():
        if not await account.try_auth():
            raise ValueError

    def done(success: bool):
        if success:
            if on_success:
                on_success()
            return

        Notifier.send(_("Authentication failed"))

        if on_failure:
            on_failure()

    tasks.create(auth(), done)


def register(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
):
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth():
        if not await account.register():
            raise ValueError

    def done(success: bool):
        if success:
            if on_success:
                on_success()
            return

        Notifier.send(_("Registration failed, try another address"))

        if on_failure:
            on_failure()

    tasks.create(auth(), done)


def log_out():
    """Remove the user's local account."""
    for profile in store.profiles.values():
        profile.set_from_profile(None)

    for data in (
        store.profiles,
        store.address_book,
        store.contact_requests,
        store.broadcasts,
        store.inbox,
        store.outbox,
        store.sent,
    ):
        data.clear()

    for key in (
        "address",
        "sync-interval",
        "empty-trash-interval",
        "trusted-domains",
        "contact-requests",
        "unread-messages",
        "trashed-messages",
        "deleted-messages",
    ):
        store.settings.reset(key)

    keyring.delete_password(store.secret_service, client.user.address)

    rmtree(core.data_dir, ignore_errors=True)

    for field in fields(model.User):
        delattr(client.user, field.name)


async def delete():
    """Permanently delete the user's account."""
    try:
        await account.delete()
    except WriteError:
        Notifier.send(_("Failed to delete account"))
        return

    log_out()
