# contact_row.py
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

from gi.repository import Adw, Gdk, GObject, Gtk

from openemail import shared


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/contact-row.ui")
class MailContactRow(Gtk.ListBoxRow):
    """A row showing a user's name, address, and profile image."""

    __gtype_name__ = "MailContactRow"

    has_name = GObject.Property(type=bool, default=False)
    profile_image = GObject.Property(type=Gdk.Paintable)

    _address: str | None = None
    _name: str | None = None

    @GObject.Property(type=str)
    def address(self) -> str | None:
        """Get the user's Mail/HTTPS address."""
        return self._address

    @address.setter
    def address(self, address: str) -> None:
        self._address = address
        self.has_name = address != self.name

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the user's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name
        self.has_name = name != self.address
