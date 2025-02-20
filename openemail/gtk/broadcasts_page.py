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
from openemail.gtk.message_row import MailMessageRow
from openemail.message import Envelope
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/broadcasts-page.ui")
class MailBroadcastsPage(Adw.NavigationPage):
    """A page listing the user's broadcast messages."""

    __gtype_name__ = "MailBroadcastsPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()

    message_view: Gtk.Label = Gtk.Template.Child()

    def update_broadcasts_list(self, loading: bool = False) -> None:
        """Update the list of broadcasts.

        If `loading` is set to True, present a loading page instead.
        """
        self.sidebar.remove_all()

        if loading:
            self.sidebar.set_placeholder(Adw.Spinner())  # type: ignore
            return

        self.sidebar.set_placeholder()
        for broadcast in shared.broadcasts:
            self.sidebar.append(
                MailMessageRow(
                    name=shared.get_name(broadcast.envelope.author),  # type: ignore
                    date=broadcast.envelope.date.strftime("%x"),  # type: ignore
                    subject=broadcast.envelope.subject,  # type: ignore
                    message=broadcast.message,  # type: ignore
                    profile_image=shared.photo_book.get(broadcast.envelope.author),  # type: ignore
                )
            )

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: Gtk.ListBoxRow) -> None:
        if not row:
            return

        self.split_view.set_show_content(True)

        try:
            self.message_view.set_label(shared.broadcasts[row.get_index()].message)
        except IndexError:
            pass
