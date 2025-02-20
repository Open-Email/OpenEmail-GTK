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
    """A page with the contents of the user's address book."""

    __gtype_name__ = "MailContactsPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()

    profile_page: MailProfilePage = Gtk.Template.Child()  # type: ignore

    def update_contacts_list(self, loading: bool = False) -> None:
        """Update the list of contacts.

        If `loading` is set to True, present a loading page instead.
        """
        self.sidebar.remove_all()

        if loading:
            self.sidebar.set_placeholder(Adw.Spinner())  # type: ignore
            return

        self.sidebar.set_placeholder()

        for contact, profile in shared.address_book.items():
            name = shared.get_name(contact)

            self.sidebar.append(
                box := Gtk.Box(
                    margin_top=12,
                    margin_bottom=12,
                )
            )
            box.append(
                Adw.Avatar(
                    size=32,
                    text=name,
                    show_initials=True,
                    custom_image=shared.photo_book.get(contact),
                    margin_end=6,
                )
            )

            box.append(
                vbox := Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL,
                    valign=Gtk.Align.CENTER,
                    margin_start=6,
                )
            )
            vbox.append(
                Gtk.Label(
                    label=name,
                    ellipsize=Pango.EllipsizeMode.END,
                    halign=Gtk.Align.START,
                )
            )
            if name != contact.address:
                (
                    label := Gtk.Label(
                        label=contact.address,
                        ellipsize=Pango.EllipsizeMode.END,
                        halign=Gtk.Align.START,
                    )
                ).add_css_class("caption")
                vbox.append(label)

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: Gtk.ListBoxRow) -> None:
        if not row:
            return

        self.split_view.set_show_content(True)

        index = row.get_index()

        try:
            self.profile_page.profile = list(shared.address_book.values())[index]
            self.profile_page.paintable = list(shared.photo_book.values())[index]
        except IndexError:
            pass
