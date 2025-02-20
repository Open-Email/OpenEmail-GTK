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

    _name: str | None = None
    _address: str | None = None
    _profile_image: Gdk.Paintable | None = None

    _has_name: bool = False

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the user's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name
        self.has_name = name != self.address

    @GObject.Property(type=str)
    def address(self) -> str | None:
        """Get the user's Mail/HTTPS address."""
        return self._address

    @address.setter
    def address(self, address: str) -> None:
        self._address = address
        self.has_name = address != self._name

    @GObject.Property(type=bool, default=True)
    def has_name(self) -> bool:
        """Whether the user has a name."""
        return self._has_name

    @has_name.setter
    def has_name(self, has_name: bool) -> None:
        self._has_name = has_name

    @GObject.Property(type=Gdk.Paintable)
    def profile_image(self) -> Gdk.Paintable | None:
        """Get the user's profile image."""
        return self._profile_image

    @profile_image.setter
    def profile_image(self, profile_image: Gdk.Paintable | None) -> None:
        self._profile_image = profile_image
