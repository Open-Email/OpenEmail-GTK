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
from typing import Any

import keyring
from gi.repository import Adw, Gtk

from openemail import shared
from openemail.gtk.auth_view import MailAuthView
from openemail.gtk.content_view import MailContentView
from openemail.user import User


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class MailWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MailWindow"

    stack: Gtk.Stack = Gtk.Template.Child()

    auth_view: MailAuthView = Gtk.Template.Child()  # type: ignore
    content_view: MailContentView = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if not (user := self.__get_local_user()):
            return

        shared.user = user
        self.stack.set_visible_child(self.content_view)

    @Gtk.Template.Callback()
    def _on_auth(self, *_args: Any) -> None:
        if not shared.user:
            return

        shared.schema.set_string("address", shared.user.address.address)
        keyring.set_password(
            f"{shared.APP_ID}.Keys",
            shared.user.address.address,
            json.dumps(
                {
                    "privateEncryptionKey": shared.user.private_encryption_key.string,
                    "privateSigningKey": shared.user.private_signing_key.string,
                }
            ),
        )

        self.stack.set_visible_child(self.content_view)

    def __get_local_user(self) -> None | User:
        if not (
            (address := shared.schema.get_string("address"))
            and (keys := keyring.get_password(shared.secret_service, address))
            and (keys := json.loads(keys))
            and (encryption_key := keys.get("privateEncryptionKey"))
            and (signing_key := keys.get("privateSigningKey"))
        ):
            return None

        try:
            return User(address, encryption_key, signing_key)
        except ValueError:
            return None
