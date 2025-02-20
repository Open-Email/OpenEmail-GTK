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

import sys
from typing import Any, Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import json

import keyring
from gi.repository import Adw, Gio

from openemail import shared
from openemail.gtk.preferences import MailPreferences
from openemail.gtk.window import MailWindow
from openemail.user import User


class MailApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self) -> None:
        super().__init__(
            application_id=shared.APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.create_action("quit", lambda *_: self.quit(), ("<primary>q",))
        self.create_action("about", self.on_about_action)
        self.create_action("preferences", self.on_preferences_action)
        self.create_action("sync", self.on_sync_action)

        if not (user := self.__get_local_user()):
            return

        shared.user = user

    def do_activate(self) -> None:
        """Raise the application's main window, creating it if necessary.

        Called when the application is activated.
        """
        (self.get_active_window() or MailWindow(application=self)).present()  # type: ignore

    def on_about_action(self, *_args: Any) -> None:
        """Present the about dialog."""
        about = Adw.AboutDialog.new_from_appdata(
            f"{shared.PREFIX}/{shared.APP_ID}.metainfo.xml"
        )
        about.set_developers(("kramo https://kramo.page",))
        about.set_designers(
            (
                "Varti Studio https://varti-studio.com",
                "kramo https://kramo.page",
            )
        )
        about.set_copyright("© 2025 Mercata Sagl")
        # Translators: Replace "translator-credits" with your name/username,
        # and optionally an email or URL.
        about.set_translator_credits(_("translator-credits"))
        about.present(self.get_active_window())

    def on_preferences_action(self, *_args: Any) -> None:
        """Present the preferences dialog."""
        if (
            isinstance(win := self.get_active_window(), Adw.ApplicationWindow)
            and win.get_visible_dialog()
        ):
            return

        MailPreferences().present(win)  # type: ignore

    def on_sync_action(self, *_args: Any) -> None:
        """Sync remote content."""
        if not isinstance(win := self.get_active_window(), MailWindow):  # type: ignore
            return

        win.content_view.load_content(first_sync=False)  # type: ignore

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

    def __get_local_user(self) -> None | User:
        if not (
            (address := shared.schema.get_string("address"))
            and (keys := keyring.get_password(shared.secret_service, address))
            and (keys := json.loads(keys))
            and (encryption_key := keys.get("privateEncryptionKey"))
            and (signing_key := keys.get("privateSigningKey"))
        ):
            return None

        try:
            return User(address, encryption_key, signing_key)
        except ValueError:
            return None


def main() -> int:
    """Run the application."""
    return MailApplication().run(sys.argv)
