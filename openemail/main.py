# main.py
#
# Authors: kramo
# Copyright 2025 Mercata Sagl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later


import gi

from openemail.core.crypto import get_keys

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Sequence

import keyring
from gi.repository import Adw, Gio

from openemail import APP_ID, PREFIX, log_file, secret_service, settings

from .core.model import Address
from .mail import user
from .widgets.preferences import MailPreferences
from .widgets.window import MailWindow


class MailApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.create_action("sync", self.on_sync_action)
        self.create_action("preferences", self.on_preferences_action)
        self.create_action("about", self.on_about_action)
        self.create_action(
            "quit",
            lambda *_: win.close() if (win := self.get_active_window()) else None,
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
            user.address = Address(address)
            user.public_encryption_key, user.private_encryption_key = get_keys(
                encryption_key,
            )
            user.public_signing_key, user.private_signing_key = get_keys(
                signing_key,
            )
        except ValueError:
            return

    def do_activate(self) -> None:
        """Raise the application's main window, creating it if necessary.

        Called when the application is activated.
        """
        (self.get_active_window() or MailWindow(application=self)).present()

    def on_about_action(self, *_args: Any) -> None:
        """Present the about dialog."""
        about = Adw.AboutDialog.new_from_appdata(f"{PREFIX}/{APP_ID}.metainfo.xml")
        about.set_developers(("kramo https://kramo.page",))
        about.set_designers(
            (
                "kramo https://kramo.page",
                "Varti Studio https://varti-studio.com",
            )
        )
        about.set_copyright("© 2025 Mercata Sagl")
        # Translators: Replace "translator-credits" with your name/username,
        # and optionally an email or URL.
        about.set_translator_credits(_("translator-credits"))

        try:
            about.set_debug_info(log_file.read_text())
        except FileNotFoundError:
            pass
        else:
            about.set_debug_info_filename(log_file.name)

        about.present(self.get_active_window())

    def on_preferences_action(self, *_args: Any) -> None:
        """Present the preferences dialog."""
        if (
            isinstance(win := self.get_active_window(), Adw.ApplicationWindow)
            and win.get_visible_dialog()
        ):
            return

        MailPreferences().present(win)

    def on_sync_action(self, *_args: Any) -> None:
        """Sync remote content."""
        if not isinstance(win := self.get_active_window(), MailWindow):
            return

        win.content_view.load_content(first_sync=False)

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


def main() -> int:
    """Run the application."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s: %(name)s %(module)s:%(lineno)d %(message)s",
        handlers=(
            (
                logging.StreamHandler(),
                RotatingFileHandler(
                    log_file,
                    maxBytes=1000000,
                ),
            )
        ),
    )

    return MailApplication().run(sys.argv)
