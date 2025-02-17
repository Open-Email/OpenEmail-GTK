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

from gi.repository import Adw, Gtk, Pango

from openemail import shared
from openemail.gtk.profile_page import MailProfilePage
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    __gtype_name__ = "MailContactsPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()

    profile_page: MailProfilePage = Gtk.Template.Child()  # type: ignore

    address_book: tuple[Address, ...] = (
        Address("kramo@open.email"),
        Address("support@open.email"),
        Address("john+tag@mymail.com"),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.sidebar.connect("row-selected", self.__on_row_selected)

        for entry in self.address_book:
            self.sidebar.append(
                box := Gtk.Box(
                    margin_top=12,
                    margin_bottom=12,
                )
            )
            box.append(
                Adw.Avatar(
                    size=32,
                    text=entry.address,
                    show_initials=True,
                    margin_end=6,
                )
            )
            box.append(
                Gtk.Label(
                    label=entry.address,
                    ellipsize=Pango.EllipsizeMode.END,
                )
            )

    def __on_row_selected(self, _obj: Any, row: Gtk.ListBoxRow) -> None:
        self.split_view.set_show_content(True)
        self.profile_page.address = self.address_book[row.get_index()]
