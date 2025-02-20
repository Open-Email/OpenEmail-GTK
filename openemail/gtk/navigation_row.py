# navigation_row.py
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

from gi.repository import Gdk, GObject, Gtk

from openemail import shared


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/navigation-row.ui")
class MailNavigationRow(Gtk.ListBoxRow):
    """An item in the main sidebar."""

    __gtype_name__ = "MailNavigationRow"

    _label: str | None = None
    _icon_name: str | None = None

    @GObject.Property(type=str)
    def label(self) -> str | None:
        """Get the item's label."""
        return self._label

    @label.setter
    def label(self, label: str) -> None:
        self._label = label

    @GObject.Property(type=str)
    def icon_name(self) -> str | None:
        """Get the item's icon."""
        return self._icon_name

    @icon_name.setter
    def icon_name(self, icon_name: str) -> None:
        self._icon_name = icon_name
