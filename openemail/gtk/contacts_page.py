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

from locale import strcoll
from typing import Any

from gi.repository import Adw, Gdk, Gio, GObject, Gtk

from openemail import shared
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.profile_view import MailProfileView
from openemail.network import fetch_contacts
from openemail.user import Address, Profile


class MailContact(GObject.Object):
    """A contact in ther user's address book."""

    __gtype_name__ = "MailContact"

    has_name = GObject.Property(type=bool, default=False)
    profile_image = GObject.Property(type=Gdk.Paintable)

    _address: str | None = None
    _name: str | None = None

    @GObject.Property(type=str)
    def address(self) -> str | None:
        """Get the user's Mail/HTTPS address."""
        return self._address

    @address.setter
    def address(self, address: str) -> None:
        self._address = address
        self.has_name = address != self.name

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the user's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name
        self.has_name = name != self.address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "MailContactsPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    profile_view: MailProfileView = Gtk.Template.Child()  # type: ignore

    contacts: Gio.ListStore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.contacts = Gio.ListStore.new(MailContact)
        self.content.model = (
            selection := Gtk.SingleSelection(
                autoselect=False,
                model=Gtk.SortListModel.new(
                    self.contacts,
                    Gtk.CustomSorter.new(lambda a, b, _: strcoll(a.name, b.name)),  # type: ignore
                ),
            )
        )
        selection.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{shared.PREFIX}/gtk/contact-row.ui"
        )

    def set_loading(self, loading: bool) -> None:
        """Set whether or not to display a spinner."""
        self.content.set_loading(loading)

    def update_contacts_list(self, contacts: dict[Address, Profile | None]) -> None:
        """Update the list of contacts."""
        self.contacts.remove_all()
        for contact, profile in contacts.items():
            self.contacts.append(
                MailContact(
                    address=str(contact),  # type: ignore
                    name=shared.get_name(contact),  # type: ignore
                    profile_image=shared.get_profile_image(contact),  # type: ignore
                )
            )

        self.set_loading(False)

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not isinstance(selected := selection.get_selected_item(), MailContact):
            return

        try:
            address = Address(selected.address)
            self.profile_view.profile = shared.address_book[address]
            self.profile_view.paintable = shared.photo_book[address]
        except (IndexError, ValueError):
            pass

        self.content.split_view.set_show_content(True)
