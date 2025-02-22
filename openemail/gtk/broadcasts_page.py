# broadcasts_page.py
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

from gi.repository import Adw, GLib, Gtk, Pango

from openemail import shared
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.message_row import MailMessageRow
from openemail.gtk.message_view import MailMessageView
from openemail.message import Envelope
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/broadcasts-page.ui")
class MailBroadcastsPage(Adw.NavigationPage):
    """A page listing the user's broadcast messages."""

    __gtype_name__ = "MailBroadcastsPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    message_view: MailMessageView = Gtk.Template.Child()  # type: ignore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.content.on_row_selected = self.__on_row_selected

    def update_broadcasts_list(self, loading: bool = False) -> None:
        """Update the list of broadcasts.

        If `loading` is set to True, present a loading page instead.
        """
        self.content.sidebar.remove_all()

        if loading:
            self.content.sidebar.set_placeholder(Adw.Spinner())  # type: ignore
            return

        self.content.sidebar.set_placeholder()
        for broadcast in shared.broadcasts:
            self.content.sidebar.append(MailMessageRow(broadcast))

    def __on_row_selected(self, row: MailMessageRow) -> None:  # type: ignore
        self.message_view.set_from_message(row.message)
