# contacts_page.py
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

from gi.repository import Adw, GLib, Gtk, Pango

from openemail import shared
from openemail.gtk.contact_row import MailContactRow
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.profile_view import MailProfileView
from openemail.network import fetch_contacts
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "MailContactsPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    profile_view: MailProfileView = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.content.on_row_selected = self.__on_row_selected

    def update_contacts_list(self, loading: bool = False) -> None:
        """Update the list of contacts.

        If `loading` is set to True, present a loading page instead.
        """
        self.content.sidebar.remove_all()

        if loading:
            self.content.sidebar.set_placeholder(Adw.Spinner())  # type: ignore
            return

        self.content.sidebar.set_placeholder()

        for contact, profile in shared.address_book.items():
            self.content.sidebar.append(
                MailContactRow(
                    address=contact.address,  # type: ignore
                    name=shared.get_name(contact),  # type: ignore
                    profile_image=shared.photo_book.get(contact),  # type: ignore
                )
            )

    def __on_row_selected(self, row: Gtk.ListBoxRow) -> None:
        try:
            address = list(shared.address_book)[row.get_index()]
            self.profile_view.profile = shared.address_book[address]
            self.profile_view.paintable = shared.photo_book[address]
        except IndexError:
            pass
