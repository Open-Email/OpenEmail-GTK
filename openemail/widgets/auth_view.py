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

from openemail import shared
from openemail.core.network import try_auth
from openemail.core.user import User
from openemail.widgets.form import MailForm


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/auth-view.ui")
class MailAuthView(Adw.Bin):
    """A view prompting the user to log in."""

    __gtype_name__ = "MailAuthView"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
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
        self.email_status_page.set_icon_name(shared.APP_ID)

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
            user = User(
                self.email_entry.get_text(),
                self.encryption_key_entry.get_text(),
                self.signing_key_entry.get_text(),
            )
        except ValueError:
            self.__warn(_("Incorrect key format"))
            return

        async def authenticate() -> None:
            self.set_property("button-child-name", "spinner")
            if not await try_auth(user):
                self.__warn(_("Authentication failed"))
                self.button_child_name = "label"
                return

            shared.user = user
            self.emit("authenticated")
            self.button_child_name = "label"

            GLib.timeout_add_seconds(1, self.email_form.reset)
            GLib.timeout_add_seconds(1, self.navigation_view.pop)
            GLib.timeout_add_seconds(1, self.auth_form.reset)

        shared.run_task(authenticate())

    def __warn(self, warning: str) -> None:
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=warning,
                priority=Adw.ToastPriority.HIGH,
            )
        )
