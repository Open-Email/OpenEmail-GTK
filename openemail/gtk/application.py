# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any, override

import keyring
from gi.repository import Adw, Gio

import openemail as app
from openemail import (
    APP_ID,
    PREFIX,
    Address,
    KeyPair,
    log_file,
    secret_service,
    settings,
)

from .preferences import Preferences
from .window import Window


class Application(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id=APP_ID)
        self._create_action("preferences", self._preferences, ("<primary>comma",))
        self._create_action("about", self._about)
        self._create_action("quit", self._quit, ("<primary>q",))

        if interval := settings.get_uint("empty-trash-interval"):
            deleted = set[str]()
            new_trashed = list[str]()

            today = datetime.now(UTC).date()
            for message in settings.get_strv("trashed-messages"):
                ident, timestamp = message.rsplit(maxsplit=1)

                try:
                    trashed = date.fromisoformat(timestamp)
                except ValueError:
                    continue

                if today.day - trashed.day >= interval:
                    deleted.add(ident)
                else:
                    new_trashed.append(message)

            settings.set_strv("trashed-messages", new_trashed)
            settings.set_strv(
                "deleted-messages",
                tuple(set(settings.get_strv("deleted-messages")) | deleted),
            )

        if not (
            (address := settings.get_string("address"))
            and (keys := keyring.get_password(secret_service, address))
            and (keys := json.loads(keys))
            and (encryption_key := keys.get("privateEncryptionKey"))
            and (signing_key := keys.get("privateSigningKey"))
        ):
            return

        try:
            app.user.address = Address(address)
            app.user.encryption_keys = KeyPair.from_b64(encryption_key)
            app.user.signing_keys = KeyPair.from_b64(signing_key)
        except ValueError:
            return

    @override
    def do_activate(self):
        (self.props.active_window or Window(application=self)).present()

    def _create_action(
        self,
        name: str,
        callback: Callable[..., Any],
        shortcuts: Sequence[str] | None = None,
    ):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def _about(self, *_args):
        about = Adw.AboutDialog.new_from_appdata(f"{PREFIX}/{APP_ID}.metainfo.xml")
        about.props.developers = ["kramo https://kramo.page"]
        about.props.designers = [
            "kramo https://kramo.page",
            "Varti Studio https://varti-studio.com",
        ]
        about.props.copyright = "© 2025 Mercata Sagl"
        # Translators: Replace "translator-credits" with your name/username,
        # and optionally an email or URL.
        about.props.translator_credits = _("translator-credits")

        try:
            about.props.debug_info = log_file.read_text()
        except FileNotFoundError:
            pass
        else:
            about.props.debug_info_filename = log_file.name

        about.present(self.props.active_window)

    def _preferences(self, *_args):
        if (
            isinstance(win := self.props.active_window, Adw.ApplicationWindow)
            and win.props.visible_dialog
        ):
            return

        Preferences().present(win)

    def _quit(self, *_args):
        if not (win := self.props.active_window):
            return

        win.close()
