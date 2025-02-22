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
from gi.repository import Adw, Gtk

from openemail import shared
from openemail.gtk.auth_view import MailAuthView
from openemail.gtk.content_view import MailContentView


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class MailWindow(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "MailWindow"

    stack: Gtk.Stack = Gtk.Template.Child()

    auth_view: MailAuthView = Gtk.Template.Child()  # type: ignore
    content_view: MailContentView = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if not shared.user:
            return

        self.content_view.load_content()
        self.stack.set_visible_child(self.content_view)

    @Gtk.Template.Callback()
    def _on_auth(self, *_args: Any) -> None:
        if not shared.user:
            return

        shared.schema.set_string("address", str(shared.user.address))
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

        self.content_view.load_content()
        self.stack.set_visible_child(self.content_view)
