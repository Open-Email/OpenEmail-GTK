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

from gi.repository import Adw, Gtk

from openemail import shared
from openemail.gtk.contact_row import MailContactRow
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.profile_view import MailProfileView
from openemail.network import fetch_contacts
from openemail.user import Address, Profile


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "MailContactsPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    profile_view: MailProfileView = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.content.on_row_selected = self.__on_row_selected

    def set_loading(self, loading: bool) -> None:
        """Set whether or not to display a spinner when there is no content."""
        self.content.sidebar.set_placeholder(Adw.Spinner() if loading else None)  # type: ignore

    def update_contacts_list(self, contacts: dict[Address, Profile | None]) -> None:
        """Update the list of contacts."""
        self.content.sidebar.remove_all()
        for contact, profile in contacts.items():
            self.content.sidebar.append(
                MailContactRow(
                    address=str(contact),  # type: ignore
                    name=shared.get_name(contact),  # type: ignore
                    profile_image=shared.get_profile_image(contact),  # type: ignore
                )
            )

        self.set_loading(False)

    def __on_row_selected(self, row: Gtk.ListBoxRow) -> None:
        try:
            address = list(shared.address_book)[row.get_index()]
            self.profile_view.profile = shared.address_book[address]
            self.profile_view.paintable = shared.photo_book[address]
        except IndexError:
            pass
