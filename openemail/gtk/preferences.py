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
from gi.repository import Adw, Gtk

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
    def _confirm_remove(self, *_args: Any) -> None:
        if not shared.user:
            return

        shared.schema.set_string("address", "")
        keyring.delete_password(shared.secret_service, shared.user.address.address)
        shared.user = None

        if not isinstance(root := self.get_root(), MailWindow):  # type: ignore
            return

        root.stack.set_visible_child(root.auth_view)  # type: ignore
        self.force_close()
