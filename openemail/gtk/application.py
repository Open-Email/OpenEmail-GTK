# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import json
from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import override

import keyring
from gi.repository import Adw

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

        self.add_action_entries(
            (
                ("preferences", lambda *_: self._preferences()),
                ("about", lambda *_: self._about()),
                ("quit", lambda *_: self._quit()),
                ("undo", lambda *_: app.notifier.undo()),
            )
        )

        self.set_accels_for_action("app.preferences", ("<primary>comma",))
        self.set_accels_for_action("app.quit", ("<primary>q",))
        self.set_accels_for_action("app.undo", ("<primary>z",))

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

    def _preferences(self):
        win = self.props.active_window
        if not (isinstance(win, Adw.ApplicationWindow) and win.props.visible_dialog):
            Preferences().present(win)

    def _about(self):
        about = Adw.AboutDialog.new_from_appdata(f"{PREFIX}/{APP_ID}.metainfo.xml")

        about.props.copyright = "© 2025 OpenEmail SA"
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

    def _quit(self):
        if win := self.props.active_window:
            win.close()

    @staticmethod
    def _get_expired_trash_items(interval: int) -> Generator[str]:
        today = datetime.now(UTC).date()
        for msg in store.settings.get_strv("trashed-messages"):
            ident, timestamp = msg.rsplit(maxsplit=1)
            with suppress(ValueError):
                if (today - date.fromisoformat(timestamp)).days >= interval:
                    yield ident
