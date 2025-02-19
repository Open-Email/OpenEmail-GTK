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
from openemail.messages import Envelope
from openemail.network import fetch_broadcasts
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/broadcasts-page.ui")
class MailBroadcastsPage(Adw.NavigationPage):
    __gtype_name__ = "MailBroadcastsPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()

    message_view: Gtk.Label = Gtk.Template.Child()

    broadcasts: tuple[tuple[Envelope, str], ...] = ()

    def update_broadcasts_list(self) -> None:
        """Updates the broadcasts list of the user by fetching new data remotely."""
        if not shared.user:
            return

        self.sidebar.remove_all()
        self.sidebar.set_placeholder(Adw.Spinner())  # type: ignore

        def update_broadcasts() -> None:
            if not shared.user:
                return

            GLib.idle_add(
                self.__update_broadcasts_list,
                fetch_broadcasts(shared.user, Address("jamie@open.email")),
            )

        GLib.Thread.new(None, update_broadcasts)

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: Gtk.ListBoxRow) -> None:
        self.split_view.set_show_content(True)
        self.message_view.set_label(self.broadcasts[row.get_index()][1])

    def __update_broadcasts_list(
        self, broadcasts: tuple[tuple[Envelope, str], ...]
    ) -> None:
        self.sidebar.set_placeholder()
        self.broadcasts = broadcasts

        for broadcast in broadcasts:
            self.sidebar.append(
                box := Gtk.Box(
                    margin_top=12,
                    margin_bottom=12,
                    margin_start=6,
                    margin_end=6,
                    orientation=Gtk.Orientation.VERTICAL,
                    spacing=3,
                )
            )

            if broadcast[0].content_headers:
                box.append(hbox := Gtk.Box())
                (
                    title := Gtk.Label(
                        hexpand=True,
                        halign=Gtk.Align.START,
                        label=broadcast[0].content_headers.author.address,
                        ellipsize=Pango.EllipsizeMode.END,
                        lines=1,
                    )
                ).add_css_class("heading")
                hbox.append(title)

                (
                    date := Gtk.Label(
                        halign=Gtk.Align.END,
                        label=broadcast[0].content_headers.date.strftime("%x"),
                        ellipsize=Pango.EllipsizeMode.END,
                        lines=1,
                    )
                ).add_css_class("caption")
                hbox.append(date)

                (
                    subject := Gtk.Label(
                        halign=Gtk.Align.START,
                        label=broadcast[0].content_headers.subject,
                        ellipsize=Pango.EllipsizeMode.END,
                        lines=2,
                    )
                ).add_css_class("caption-heading")
                box.append(subject)

            (
                message := Gtk.Label(
                    halign=Gtk.Align.START,
                    hexpand=True,
                    label=broadcast[1],
                    ellipsize=Pango.EllipsizeMode.END,
                    lines=3,
                )
            ).add_css_class("caption")
            box.append(message)
