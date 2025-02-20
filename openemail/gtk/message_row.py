# message_row.py
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


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/message-row.ui")
class MailMessageRow(Gtk.ListBoxRow):
    """An item in the main sidebar."""

    __gtype_name__ = "MailMessageRow"

    _name: str | None = None
    _date: str | None = None
    _subject: str | None = None
    _message: str | None = None
    _profile_image: Gdk.Paintable | None = None

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the author's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name

    @GObject.Property(type=str)
    def date(self) -> str | None:
        """Get the message's sent date."""
        return self._date

    @date.setter
    def date(self, date: str) -> None:
        self._date = date

    @GObject.Property(type=str)
    def subject(self) -> str | None:
        """Get the message's subject."""
        return self._subject

    @subject.setter
    def subject(self, subject: str) -> None:
        self._subject = subject

    @GObject.Property(type=str)
    def message(self) -> str | None:
        """Get the message."""
        return self._message

    @message.setter
    def message(self, message: str) -> None:
        self._message = message

    @GObject.Property(type=Gdk.Paintable)
    def profile_image(self) -> Gdk.Paintable | None:
        """Get the author's profile image."""
        return self._profile_image

    @profile_image.setter
    def profile_image(self, profile_image: Gdk.Paintable) -> None:
        self._profile_image = profile_image
