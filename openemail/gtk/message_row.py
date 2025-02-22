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

from re import sub
from typing import Any

from gi.repository import Gdk, GObject, Gtk

from openemail import shared
from openemail.message import Message


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/message-row.ui")
class MailMessageRow(Gtk.ListBoxRow):
    """An item in the main sidebar."""

    __gtype_name__ = "MailMessageRow"

    message: Message | None = None

    name = GObject.Property(type=str)
    date = GObject.Property(type=str)
    subject = GObject.Property(type=str)
    contents = GObject.Property(type=str)
    stripped_contents = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    def __init__(self, message: Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if message:
            self.set_from_message(message)

    def set_from_message(self, message: Message) -> None:
        """Update properties of the row from `message`."""
        self.message = message

        self.name = shared.get_name(message.envelope.author)
        self.date = message.envelope.date.strftime("%x")
        self.subject = message.envelope.subject
        self.contents = message.contents
        self.stripped_contents = sub(r"\n+", " ", message.contents)
        self.profile_image = shared.photo_book.get(message.envelope.author)
