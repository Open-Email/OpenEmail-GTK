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
from typing import Any, Callable, Optional, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from openemail import shared
from openemail.window import MailWindow


class MailApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self) -> None:
        super().__init__(
            application_id=shared.APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.create_action("quit", lambda *_: self.quit(), ["<primary>q"])
        self.create_action("about", self.on_about_action)
        self.create_action("preferences", self.on_preferences_action)

    def do_activate(self) -> None:
        """Called when the application is activated.

        We raise the application"s main window, creating it if
        necessary.
        """
        (self.get_active_window() or MailWindow(application=self)).present()  # type: ignore

    def on_about_action(self, *_args: Any) -> None:
        """Callback for the app.about action."""
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
        # Translators: Replace "translator-credits" with your name/username, and optionally an email or URL.
        about.set_translator_credits(_("translator-credits"))
        about.present(self.props.active_window)

    def on_preferences_action(self, *_args: Any) -> None:
        """Callback for the app.preferences action."""
        print("app.preferences action activated")

    def create_action(
        self,
        name: str,
        callback: Callable,
        shortcuts: Optional[Sequence] = None,
    ) -> None:
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main() -> int:
    """The application"s entry point."""
    app = MailApplication()
    return app.run(sys.argv)
