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

from gi.repository import Adw, Gtk

from openemail import shared
from openemail.contacts_page import MailContactsPage
from openemail.sidebar_item import MailSidebarItem


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/window.ui")
class MailWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MailWindow"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()
    contacts_sidebar: Gtk.ListBox = Gtk.Template.Child()

    content: Gtk.Stack = Gtk.Template.Child()

    empty_page: Adw.StatusPage = Gtk.Template.Child()
    contacts_page: MailContactsPage = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.sidebar.connect("row-selected", self.__on_row_selected)
        self.contacts_sidebar.connect("row-selected", self.__on_contacts_selected)

    def __on_row_selected(self, _obj: Any, row: MailSidebarItem) -> None:  # type: ignore
        self.contacts_sidebar.unselect_all()
        self.sidebar.select_row(row)

        self.empty_page.set_title(row.label)
        self.empty_page.set_icon_name(row.icon_name)
        self.content.set_visible_child(self.empty_page)
        self.split_view.set_show_content(True)

    def __on_contacts_selected(self, _obj: Any, row: MailSidebarItem) -> None:  # type: ignore
        self.sidebar.unselect_all()
        self.contacts_sidebar.select_row(row)

        self.content.set_visible_child(self.contacts_page)
        self.split_view.set_show_content(True)
