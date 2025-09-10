# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
from collections.abc import Callable, Generator, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any, override

import keyring
from gi.repository import Adw, Gio

import openemail as app
from openemail import APP_ID, PREFIX, store
from openemail.core import client
from openemail.core.crypto import KeyPair
from openemail.core.model import Address

from .preferences import Preferences
from .window import Window


class Application(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id=APP_ID)
        self._add_action("preferences", self._preferences, ("<primary>comma",))
        self._add_action("about", self._about)
        self._add_action("quit", self._quit, ("<primary>q",))

        if interval := store.settings.get_uint("empty-trash-interval"):
            expired = tuple(self._get_expired_trash_items(interval))
            store.settings_discard("trashed-messages", *expired)
            store.settings_add("deleted-messages", *expired)

        if (
            (address := store.settings.get_string("address"))
            and (keys := keyring.get_password(store.secret_service, address))
            and (keys := json.loads(keys))
            and (encryption_key := keys.get("privateEncryptionKey"))
            and (signing_key := keys.get("privateSigningKey"))
        ):
            with suppress(ValueError):
                client.user.address = Address(address)
                client.user.encryption_keys = KeyPair.from_b64(encryption_key)
                client.user.signing_keys = KeyPair.from_b64(signing_key)

    @override
    def do_activate(self):
        (self.props.active_window or Window(application=self)).present()

    def _add_action(self, name: str, cb: Callable[[], Any], accels: Sequence[str] = ()):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_: cb())
        self.add_action(action)
        self.set_accels_for_action(f"app.{name}", accels)

    def _about(self):
        about = Adw.AboutDialog.new_from_appdata(f"{PREFIX}/{APP_ID}.metainfo.xml")

        about.props.copyright = "© 2025 Mercata Sagl"
        about.props.developers = ["kramo https://kramo.page"]
        about.props.designers = [
            "kramo https://kramo.page",
            "Varti Studio https://varti-studio.com",
        ]

        # Translators: Replace "translator-credits" with your name/username,
        # and optionally an email or URL.
        about.props.translator_credits = _("translator-credits")

        app.log_path.parent.mkdir(parents=True, exist_ok=True)
        app.log_path.touch(exist_ok=True)
        about.props.debug_info = app.log_path.read_text()
        about.props.debug_info_filename = app.log_path.name

        about.present(self.props.active_window)

    def _preferences(self):
        win = self.props.active_window
        if not (isinstance(win, Adw.ApplicationWindow) and win.props.visible_dialog):
            Preferences().present(win)

    def _quit(self):
        if win := self.props.active_window:
            win.close()

    @staticmethod
    def _get_expired_trash_items(interval: int) -> Generator[str]:
        today = datetime.now(UTC).date()
        for message in store.settings.get_strv("trashed-messages"):
            ident, timestamp = message.rsplit(maxsplit=1)
            with suppress(ValueError):
                if (today - date.fromisoformat(timestamp)).days >= interval:
                    yield ident
