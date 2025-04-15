# auth_view.py
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

from gi.repository import Adw, GLib, GObject, Gtk

from openemail import APP_ID, PREFIX, notifier
from openemail.core.crypto import get_keys
from openemail.core.model import Address
from openemail.mail import try_auth, user

from .form import MailForm


@Gtk.Template(resource_path=f"{PREFIX}/gtk/auth-view.ui")
class MailAuthView(Adw.Bin):
    """A view prompting the user to log in."""

    __gtype_name__ = "MailAuthView"

    navigation_view: Adw.NavigationView = Gtk.Template.Child()

    email_status_page: Adw.StatusPage = Gtk.Template.Child()
    email_entry: Adw.EntryRow = Gtk.Template.Child()
    email_form: MailForm = Gtk.Template.Child()

    keys_status_page: Adw.StatusPage = Gtk.Template.Child()
    keys_page: Adw.NavigationPage = Gtk.Template.Child()
    signing_key_entry: Adw.EntryRow = Gtk.Template.Child()
    encryption_key_entry: Adw.EntryRow = Gtk.Template.Child()
    auth_form: MailForm = Gtk.Template.Child()

    button_child_name = GObject.Property(type=str, default="label")

    authenticated = GObject.Signal()

    def __init__(self, **kwargs: Any) -> None:
        self.email_status_page.set_icon_name(APP_ID)

    @Gtk.Template.Callback()
    def _log_in(self, *args: Any) -> None:
        self.keys_status_page.set_title(self.email_entry.get_text())
        self.navigation_view.push(self.keys_page)
        self.signing_key_entry.grab_focus()

    @Gtk.Template.Callback()
    def _focus_encryption_key_entry(self, *_args: Any) -> None:
        self.encryption_key_entry.grab_focus()

    @Gtk.Template.Callback()
    def _authenticate(self, *_args: Any) -> None:
        try:
            user.address = Address(self.email_entry.get_text())
            user.public_encryption_key, user.private_encryption_key = get_keys(
                self.encryption_key_entry.get_text()
            )
            user.public_signing_key, user.private_signing_key = get_keys(
                self.signing_key_entry.get_text()
            )

        except ValueError:
            notifier.send(_("Incorrect key format"))
            return

        def success() -> None:
            self.button_child_name = "label"
            self.emit("authenticated")

            def reset() -> None:
                self.email_form.reset()
                self.navigation_view.pop()
                self.auth_form.reset()

            GLib.timeout_add_seconds(1, reset)

        self.button_child_name = "loading"
        try_auth(success, lambda: self.set_property("button-child-name", "label"))
