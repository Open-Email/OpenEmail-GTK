# window.py
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

import json
from base64 import b64encode
from typing import Any

import keyring
from gi.repository import Adw, Gio, GObject, Gtk

from openemail import APP_ID, PREFIX, mail, notifier, settings, state_settings

from .auth_view import MailAuthView
from .content_view import MailContentView


@Gtk.Template(resource_path=f"{PREFIX}/gtk/window.ui")
class MailWindow(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "MailWindow"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()

    auth_view: MailAuthView = Gtk.Template.Child()
    content_view: MailContentView = Gtk.Template.Child()

    visible_child_name = GObject.Property(type=str, default="auth")

    _quit: bool = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        state_settings.bind(
            "width",
            self,
            "default-width",
            Gio.SettingsBindFlags.DEFAULT,
        )
        state_settings.bind(
            "height",
            self,
            "default-height",
            Gio.SettingsBindFlags.DEFAULT,
        )
        state_settings.bind(
            "show-sidebar",
            self.content_view.split_view,
            "show-sidebar",
            Gio.SettingsBindFlags.DEFAULT,
        )

        self.connect("close-request", self.__close)
        notifier.connect("send", self.__on_send_notification)

        self.content_view.load_content(periodic=True)

        if not mail.user.logged_in:
            return

        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _on_auth(self, *_args: Any) -> None:
        keyring.set_password(
            f"{APP_ID}.Keys",
            str(mail.user.address),
            json.dumps(
                {
                    "privateEncryptionKey": str(mail.user.private_encryption_key),
                    "privateSigningKey": b64encode(
                        bytes(mail.user.private_signing_key)
                        + bytes(mail.user.public_signing_key)
                    ).decode("utf-8"),
                }
            ),
        )

        settings.set_string("address", str(mail.user.address))

        self.content_view.load_content()
        self.visible_child_name = "content"

    def __close(self, *_args: Any) -> bool:
        if self._quit or (not mail.is_writing()):
            return False

        def on_response(_obj: Any, response: str) -> None:
            if response != "quit":
                return

            self._quit = True
            self.close()

        (
            alert := Adw.AlertDialog.new(
                _("Upload Ongoing"),
                _("Quitting now will make you lose data such as sent messages"),
            )
        ).connect("response", on_response)
        alert.add_response("cancel", _("Cancel"))
        alert.add_response("quit", _("Quit"))
        alert.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)

        alert.present(self)
        return True

    def __on_send_notification(self, _obj: Any, title: str) -> None:
        toast = Adw.Toast(title=title, priority=Adw.ToastPriority.HIGH)

        if isinstance(dialog := self.get_visible_dialog(), Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.dismiss_all()  # type: ignore
        self.toast_overlay.add_toast(toast)
