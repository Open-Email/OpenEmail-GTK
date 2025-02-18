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
from openemail.gtk.profile_page import MailProfilePage
from openemail.network import fetch_contacts
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    __gtype_name__ = "MailContactsPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()

    profile_page: MailProfilePage = Gtk.Template.Child()  # type: ignore

    contacts: tuple[Address, ...] = ()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.sidebar.connect("row-selected", self.__on_row_selected)

    def update_contacts_list(self) -> None:
        """Updates the contact list of the user by fetching new data remotely."""
        if not shared.user:
            return

        self.sidebar.remove_all()
        self.sidebar.set_placeholder(Adw.Spinner())  # type: ignore

        def update_contacts() -> None:
            if not shared.user:
                return

            GLib.idle_add(
                self.__update_contacts_list,
                fetch_contacts(shared.user),
            )

        GLib.Thread.new(None, update_contacts)

    def __update_contacts_list(self, contacts: tuple[Address, ...]) -> None:
        self.sidebar.set_placeholder()
        self.contacts = contacts

        for contact in contacts:
            self.sidebar.append(
                box := Gtk.Box(
                    margin_top=12,
                    margin_bottom=12,
                )
            )
            box.append(
                Adw.Avatar(
                    size=32,
                    text=contact.address,
                    show_initials=True,
                    margin_end=6,
                )
            )
            box.append(
                Gtk.Label(
                    label=contact.address,
                    ellipsize=Pango.EllipsizeMode.END,
                )
            )

    def __on_row_selected(self, _obj: Any, row: Gtk.ListBoxRow) -> None:
        self.split_view.set_show_content(True)
        self.profile_page.address = self.contacts[row.get_index()]
