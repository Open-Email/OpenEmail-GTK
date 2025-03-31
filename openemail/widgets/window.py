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

from openemail import shared

from .auth_view import MailAuthView
from .content_view import MailContentView


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class MailWindow(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "MailWindow"

    auth_view: MailAuthView = Gtk.Template.Child()
    content_view: MailContentView = Gtk.Template.Child()

    visible_child_name = GObject.Property(type=str, default="auth")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        shared.state_settings.bind(
            "width",
            self,
            "default-width",
            Gio.SettingsBindFlags.DEFAULT,
        )
        shared.state_settings.bind(
            "height",
            self,
            "default-height",
            Gio.SettingsBindFlags.DEFAULT,
        )
        shared.state_settings.bind(
            "show-sidebar",
            self.content_view.split_view,
            "show-sidebar",
            Gio.SettingsBindFlags.DEFAULT,
        )

        self.content_view.load_content(periodic=True)
        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _on_auth(self, *_args: Any) -> None:
        keyring.set_password(
            f"{shared.APP_ID}.Keys",
            str(shared.user.address),
            json.dumps(
                {
                    "privateEncryptionKey": str(shared.user.private_encryption_key),
                    "privateSigningKey": b64encode(
                        bytes(shared.user.private_signing_key)
                        + bytes(shared.user.public_signing_key)
                    ).decode("utf-8"),
                }
            ),
        )

        shared.settings.set_string("address", str(shared.user.address))

        self.content_view.load_content()
        self.visible_child_name = "content"
