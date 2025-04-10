# request_buttons.py
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

from gi.repository import GObject, Gtk

from openemail.core.network import new_contact
from openemail.core.user import Address
from openemail.shared import PREFIX, run_task, settings, user
from openemail.store import address_book, broadcasts, inbox


@Gtk.Template(resource_path=f"{PREFIX}/gtk/request-buttons.ui")
class MailRequestButtons(Gtk.Box):
    """Buttons to accept or decline a contact request."""

    __gtype_name__ = "MailRequestButtons"

    address = GObject.Property(type=str)

    @Gtk.Template.Callback()
    def _accept(self, *_args: Any) -> None:
        self.__remove_address()

        try:
            address = Address(self.address)
        except ValueError:
            return

        run_task(new_contact(address, user))

        address_book.add(address)
        run_task(address_book.update_profiles())
        run_task(broadcasts.update())
        run_task(inbox.update())

    @Gtk.Template.Callback()
    def _decline(self, *_args: Any) -> None:
        self.__remove_address()

    def __remove_address(self) -> None:
        try:
            (requests := settings.get_strv("contact-requests")).remove(self.address)
        except ValueError:
            return

        settings.set_strv("contact-requests", requests)
