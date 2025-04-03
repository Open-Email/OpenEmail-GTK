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

from gi.repository import GObject, Gtk

from openemail.shared import PREFIX


@Gtk.Template(resource_path=f"{PREFIX}/gtk/navigation-row.ui")
class MailNavigationRow(Gtk.ListBoxRow):
    """An item in the main sidebar."""

    __gtype_name__ = "MailNavigationRow"

    label = GObject.Property(type=str)
    icon_name = GObject.Property(type=str)
