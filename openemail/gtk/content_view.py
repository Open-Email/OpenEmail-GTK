# content_view.py
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
from openemail.gtk.broadcasts_page import MailBroadcastsPage
from openemail.gtk.contacts_page import MailContactsPage
from openemail.gtk.sidebar_item import MailSidebarItem


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/content-view.ui")
class MailContentView(Adw.BreakpointBin):
    __gtype_name__ = "MailContentView"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()
    contacts_sidebar: Gtk.ListBox = Gtk.Template.Child()

    content: Gtk.Stack = Gtk.Template.Child()

    empty_page: Adw.ToolbarView = Gtk.Template.Child()
    empty_status_page: Adw.StatusPage = Gtk.Template.Child()

    broadcasts_page: MailBroadcastsPage = Gtk.Template.Child()  # type: ignore
    contacts_page: MailContactsPage = Gtk.Template.Child()  # type: ignore

    def load_content(self) -> None:
        """Populates the content view by fetching the local user's data."""
        self.contacts_page.update_contacts_list()
        self.broadcasts_page.update_broadcasts_list()

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: MailSidebarItem | None) -> None:  # type: ignore
        if not row:
            return

        self.contacts_sidebar.unselect_all()
        self.sidebar.select_row(row)

        match row.get_index():
            case 0:
                self.content.set_visible_child(self.broadcasts_page)
            case _:
                self.empty_status_page.set_title(row.label)
                self.empty_status_page.set_icon_name(row.icon_name)
                self.content.set_visible_child(self.empty_page)

        self.split_view.set_show_content(True)

    @Gtk.Template.Callback()
    def _on_contacts_selected(self, _obj: Any, row: MailSidebarItem | None) -> None:  # type: ignore
        if not row:
            return

        self.sidebar.unselect_all()
        self.contacts_sidebar.select_row(row)

        self.content.set_visible_child(self.contacts_page)
        self.split_view.set_show_content(True)
