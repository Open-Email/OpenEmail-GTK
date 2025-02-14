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

from typing import Any

from gi.repository import Adw, GLib, Gtk, Pango

from openemail import shared
from openemail.client import Address, fetch_profile
from openemail.profile_page import MailProfilePage


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class MailWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MailWindow"

    pages_split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    pages_list: Gtk.ListBox = Gtk.Template.Child()

    content_split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    contacts_list: Gtk.ListBox = Gtk.Template.Child()

    profile_page: MailProfilePage = Gtk.Template.Child()

    address_book: tuple[Address, ...] = (
        Address("kramo@open.email"),
        Address("support@open.email"),
        Address("john+tag@mymail.com"),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.pages_list.connect(
            "row-selected",
            lambda *_: self.pages_split_view.set_show_content(True),
        )
        self.contacts_list.connect(
            "row-selected",
            lambda _obj, row: (
                self.content_split_view.set_show_content(True),
                GLib.Thread.new(
                    None, self.__load_profile, self.address_book[row.get_index()]
                ),
            ),
        )

        for entry in self.address_book:
            self.contacts_list.append(
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

    def __load_profile(self, address: Address) -> None:
        profile = fetch_profile(address)
        GLib.idle_add(self.profile_page.set_profile, profile)
