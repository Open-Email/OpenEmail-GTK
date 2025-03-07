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

from gi.repository import Adw, Gtk

from openemail import shared
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.profile_view import MailProfileView


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "MailContactsPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    profile_view: MailProfileView = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.content.model = (
            selection := Gtk.SingleSelection(
                autoselect=False,
                model=Gtk.SortListModel.new(
                    shared.address_book,
                    Gtk.CustomSorter.new(lambda a, b, _: strcoll(a.name, b.name)),  # type: ignore
                ),
            )
        )
        selection.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{shared.PREFIX}/gtk/contact-row.ui"
        )

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not isinstance(
            selected := selection.get_selected_item(), shared.MailProfile
        ):
            return

        self.profile_view.profile = selected.profile
        self.profile_view.paintable = selected.image

        self.content.split_view.set_show_content(True)
