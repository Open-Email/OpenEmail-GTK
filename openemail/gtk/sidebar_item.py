# sidebar_item.py
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

from gi.repository import GObject, Gtk

from openemail import shared


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/sidebar-item.ui")
class MailSidebarItem(Gtk.ListBoxRow):
    """An item in the main sidebar."""

    __gtype_name__ = "MailSidebarItem"

    title: Gtk.Label = Gtk.Template.Child()
    icon: Gtk.Image = Gtk.Template.Child()

    @GObject.Property(type=str)
    def label(self) -> str:
        """Get the item's label."""
        return self.title.get_label()

    @label.setter
    def label(self, label: str) -> None:
        self.title.set_label(label)

    @GObject.Property(type=str)
    def icon_name(self) -> str | None:
        """Get the item's icon."""
        return self.icon.get_icon_name()

    @icon_name.setter
    def icon_name(self, icon_name: str) -> None:
        self.icon.set_from_icon_name(icon_name)
