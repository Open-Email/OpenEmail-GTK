# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

import json
import logging
import sys
from collections.abc import Callable, Sequence
from logging.handlers import RotatingFileHandler
from typing import Any

import keyring
from gi.repository import Adw, Gio

from openemail import APP_ID, PREFIX, log_file, mail, secret_service, settings
from openemail.mail import Address, KeyPair

from .widgets.preferences import Preferences
from .widgets.window import Window


class Application(Adw.Application):
    """The main application singleton class."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.create_action("preferences", self._preferences)
        self.create_action("about", self._about)
        self.create_action(
            "quit",
            lambda *_: win.close() if (win := self.props.active_window) else None,
            ("<primary>q",),
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
            mail.user.address = Address(address)
            mail.user.encryption_keys = KeyPair.from_b64(encryption_key)
            mail.user.signing_keys = KeyPair.from_b64(signing_key)
        except ValueError:
            return

    def do_activate(self) -> None:
        """Raise the application's main window, creating it if necessary.

        Called when the application is activated.
        """
        (self.props.active_window or Window(application=self)).present()

    def create_action(
        self,
        name: str,
        callback: Callable,
        shortcuts: Sequence | None = None,
    ) -> None:
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is activated
            shortcuts: an optional list of accelerators

        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def _about(self, *_args: Any) -> None:
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

    def _preferences(self, *_args: Any) -> None:
        if (
            isinstance(win := self.props.active_window, Adw.ApplicationWindow)
            and win.props.visible_dialog
        ):
            return

        Preferences().present(win)


def main() -> int:
    """Run the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s: %(name)s %(module)s:%(lineno)d %(message)s",
        handlers=(
            (
                logging.StreamHandler(),
                RotatingFileHandler(log_file, maxBytes=1_000_000),
            )
        ),
    )

    return Application().run(sys.argv)
