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

from base64 import b64encode
from typing import Any

import keyring
from gi.repository import Adw, GLib, GObject, Gtk

from openemail import shared

from .window import MailWindow


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/preferences.ui")
class MailPreferences(Adw.PreferencesDialog):
    """The application's preferences dialog."""

    __gtype_name__ = "MailPreferences"

    confirm_remove_dialog: Adw.AlertDialog = Gtk.Template.Child()

    private_signing_key = GObject.Property(type=str)
    private_encryption_key = GObject.Property(type=str)
    public_signing_key = GObject.Property(type=str)
    public_encryption_key = GObject.Property(type=str)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if not shared.user:
            return

        self.private_signing_key = b64encode(
            bytes(shared.user.private_signing_key)
            + bytes(shared.user.public_signing_key)
        ).decode("utf-8")
        self.private_encryption_key = str(shared.user.private_encryption_key)
        self.public_signing_key = str(shared.user.public_signing_key)
        self.public_encryption_key = str(shared.user.public_encryption_key)

    @Gtk.Template.Callback()
    def _remove_account(self, *_args: Any) -> None:
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_remove(self, _obj: Any, response: str) -> None:
        if response != "remove":
            return

        if not shared.user:
            return

        for profile in shared.profiles.values():
            profile.profile = None

        shared.profiles.clear()
        shared.address_book.remove_all()
        shared.broadcasts.remove_all()
        shared.inbox.remove_all()
        shared.outbox.remove_all()

        shared.settings.set_string("address", "")
        shared.settings.set_value("trashed-message-ids", GLib.Variant.new_strv(()))

        keyring.delete_password(shared.secret_service, str(shared.user.address))

        shared.user = None

        if not isinstance(win := self.get_root(), MailWindow):
            return

        win.visible_child_name = "auth"
        self.force_close()
