# preferences.py
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

from typing import Any

import keyring
from gi.repository import Adw, GLib, Gtk

from openemail import shared
from openemail.gtk.window import MailWindow


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/preferences.ui")
class MailPreferences(Adw.PreferencesDialog):
    """The application's preferences dialog."""

    __gtype_name__ = "MailPreferences"

    confirm_remove_dialog: Adw.AlertDialog = Gtk.Template.Child()

    @Gtk.Template.Callback()
    def _remove_account(self, *_args: Any) -> None:
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_remove(self, _obj: Any, response: str) -> None:
        if response != "remove":
            return

        if not shared.user:
            return

        shared.profiles.clear()
        shared.address_book.remove_all()
        shared.broadcasts.remove_all()
        shared.inbox.remove_all()
        shared.outbox.remove_all()

        shared.settings.set_string("address", "")
        shared.settings.set_value("trashed-message-ids", GLib.Variant.new_strv(()))  #  type: ignore

        keyring.delete_password(shared.secret_service, str(shared.user.address))

        shared.user = None

        if not isinstance(win := self.get_root(), MailWindow):  # type: ignore
            return

        win.visible_child_name = "auth"  # type: ignore
        self.force_close()
