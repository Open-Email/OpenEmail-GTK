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
from dataclasses import fields
from typing import Any

import keyring
from gi.repository import Adw, GObject, Gtk

from openemail.core.user import User
from openemail.shared import PREFIX, secret_service, settings, user
from openemail.store import address_book, broadcasts, inbox, outbox, profiles

from .window import MailWindow


@Gtk.Template(resource_path=f"{PREFIX}/gtk/preferences.ui")
class MailPreferences(Adw.PreferencesDialog):
    """The application's preferences dialog."""

    __gtype_name__ = "MailPreferences"

    confirm_remove_dialog: Adw.AlertDialog = Gtk.Template.Child()
    sync_interval_combo_row: Adw.ComboRow = Gtk.Template.Child()

    private_signing_key = GObject.Property(type=str)
    private_encryption_key = GObject.Property(type=str)
    public_signing_key = GObject.Property(type=str)
    public_encryption_key = GObject.Property(type=str)

    _intervals = (0, 60, 300, 900, 1800, 3600)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.private_signing_key = b64encode(
            bytes(user.private_signing_key) + bytes(user.public_signing_key)
        ).decode("utf-8")
        self.private_encryption_key = str(user.private_encryption_key)
        self.public_signing_key = str(user.public_signing_key)
        self.public_encryption_key = str(user.public_encryption_key)

        try:
            self.sync_interval_combo_row.set_selected(
                self._intervals.index(
                    settings.get_uint("sync-interval"),
                )
            )
        except ValueError:
            pass

    @Gtk.Template.Callback()
    def _sync_interval_selected(self, row: Adw.ComboRow, *_args: Any) -> None:
        settings.set_uint("sync-interval", self._intervals[row.get_selected()])

    @Gtk.Template.Callback()
    def _remove_account(self, *_args: Any) -> None:
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_remove(self, _obj: Any, response: str) -> None:
        if response != "remove":
            return

        for profile in profiles.values():
            profile.profile = None

        profiles.clear()
        address_book.clear()
        broadcasts.clear()
        inbox.clear()
        outbox.clear()

        settings.reset("address")
        settings.reset("sync-interval")
        settings.reset("trashed-message-ids")

        keyring.delete_password(secret_service, str(user.address))

        for field in fields(User):
            delattr(user, field.name)

        if not isinstance(win := self.get_root(), MailWindow):
            return

        win.visible_child_name = "auth"
        self.force_close()
