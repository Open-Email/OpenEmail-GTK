# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable
from dataclasses import fields
from shutil import rmtree
from typing import Any

import keyring

from openemail import app
from openemail.core import client, model
from openemail.core.client import WriteError, user

from . import Notifier, mail
from .store import secret_service, settings


def try_auth(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
) -> None:
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth() -> None:
        if not await client.try_auth():
            raise ValueError

    def done(success: bool) -> None:
        if success:
            if on_success:
                on_success()
            return

        Notifier.send(_("Authentication failed"))

        if on_failure:
            on_failure()

    app.create_task(auth(), done)


def register(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
) -> None:
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth() -> None:
        if not await client.register():
            raise ValueError

    def done(success: bool) -> None:
        if success:
            if on_success:
                on_success()
            return

        Notifier.send(_("Registration failed, try another address"))

        if on_failure:
            on_failure()

    app.create_task(auth(), done)


def log_out() -> None:
    """Remove the user's local account."""
    for profile in mail.profiles.values():
        profile.set_from_profile(None)

    mail.profiles.clear()
    mail.address_book.clear()
    mail.contact_requests.clear()
    mail.broadcasts.clear()
    mail.inbox.clear()
    mail.outbox.clear()

    settings.reset("address")
    settings.reset("sync-interval")
    settings.reset("empty-trash-interval")
    settings.reset("trusted-domains")
    settings.reset("contact-requests")
    settings.reset("unread-messages")
    settings.reset("trashed-messages")
    settings.reset("deleted-messages")

    keyring.delete_password(secret_service, str(user.address))

    rmtree(client.data_dir, ignore_errors=True)

    for field in fields(model.User):
        delattr(user, field.name)


async def delete() -> None:
    """Permanently delete the user's account."""
    try:
        await client.delete_account()
    except WriteError:
        Notifier.send(_("Failed to delete account"))
        return

    log_out()
