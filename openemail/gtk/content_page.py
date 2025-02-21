# content_page.py
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

from typing import Any, Callable

from gi.repository import Adw, GLib, GObject, Gtk

from openemail import shared
from openemail.gtk.contact_row import MailContactRow
from openemail.gtk.profile_page import MailProfilePage
from openemail.network import fetch_contacts
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/content-page.ui")
class MailContentPage(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "MailContentPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()

    on_row_selected: Callable[[Gtk.ListBoxRow], Any] | None = None

    _title: str = _("Content")
    _details: Gtk.Widget | None = None

    @GObject.Property(type=str, default=_("Content"))
    def title(self) -> str | None:
        """Get the page's title."""
        return self._title

    @title.setter
    def title(self, title: str) -> None:
        self._title = title

    @GObject.Property(type=Gtk.Widget)
    def details(self) -> Gtk.Widget | None:
        """Get the page's details view."""
        return self._details

    @details.setter
    def details(self, details: Gtk.Widget | None) -> None:
        self._details = details

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: Gtk.ListBoxRow) -> None:
        if not row:
            return

        if self.on_row_selected:
            self.on_row_selected(row)

        self.split_view.set_show_content(True)
