# content_page.py
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

from typing import Any, Callable

from gi.repository import Adw, GLib, GObject, Gtk

from openemail import shared
from openemail.gtk.profile_view import MailProfileView
from openemail.network import send_message
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/content-page.ui")
class MailContentPage(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "MailContentPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()

    factory = GObject.Property(type=Gtk.ListItemFactory)

    sidebar_child_name = GObject.Property(type=str, default="content")

    title = GObject.Property(type=str, default=_("Content"))
    details = GObject.Property(type=Gtk.Widget)

    compose_dialog: Adw.Dialog = Gtk.Template.Child()
    broadcast_switch: Gtk.Switch = Gtk.Template.Child()
    subject: Gtk.Text = Gtk.Template.Child()
    readers: Gtk.Text = Gtk.Template.Child()
    body: Gtk.TextView = Gtk.Template.Child()

    _model: Gtk.SelectionModel
    _loading: bool

    show_sidebar = GObject.Signal()

    @GObject.Property(type=bool, default=False)
    def loading(self) -> bool:
        """Get whether or not to display a loading indicator in case the page is empty."""
        return self._loading

    @loading.setter
    def loading(self, loading: bool) -> None:
        self._loading = loading
        self.__update_loading()

    @GObject.Property(type=Gtk.SelectionModel)
    def model(self) -> Gtk.SelectionModel:
        """Get the selection model."""
        return self._model

    @model.setter
    def model(self, model: Gtk.SelectionModel) -> None:
        self._model = model

        model.connect("items-changed", self.__update_loading)

    @Gtk.Template.Callback()
    def _show_sidebar(self, *_args: Any) -> None:
        if not isinstance(
            split_view := getattr(
                getattr(self.get_root(), "content_view", None),
                "split_view",
                None,
            ),
            Adw.OverlaySplitView,
        ):
            return

        split_view.set_show_sidebar(not split_view.get_show_sidebar())

    @Gtk.Template.Callback()
    def _new_message(self, *_args: Any) -> None:
        self.readers.set_text("")
        self.subject.set_text("")
        self.body.get_buffer().set_text("")
        self.broadcast_switch.set_active(False)

        self.compose_dialog.present(self)
        self.readers.grab_focus()

    @Gtk.Template.Callback()
    def _send_message(self, *_args: Any) -> None:
        if not shared.user:
            return

        readers: list[Address] = []
        if not self.broadcast_switch.get_active():
            for reader in self.readers.get_text().split(","):
                try:
                    readers.append(Address(reader.strip()))
                except ValueError:
                    return

        shared.run_task(
            send_message(
                shared.user,
                readers,
                self.subject.get_text(),
                (buffer := self.body.get_buffer()).get_text(
                    buffer.get_start_iter(),
                    buffer.get_end_iter(),
                    False,
                ),
            ),
            lambda: shared.run_task(shared.update_outbox()),
        )

        self.compose_dialog.force_close()

    def __update_loading(self, *_args: Any) -> None:
        self.sidebar_child_name = (
            "spinner" if self._loading and (not self.model.get_n_items()) else "content"
        )
