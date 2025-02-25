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
from openemail.network import fetch_contacts
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/content-page.ui")
class MailContentPage(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "MailContentPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()

    factory = GObject.Property(type=Gtk.ListItemFactory)
    model = GObject.Property(type=Gtk.SelectionModel)

    sidebar_child_name = GObject.Property(type=str, default="content")

    title = GObject.Property(type=str, default=_("Content"))
    details = GObject.Property(type=Gtk.Widget)

    @GObject.Signal(name="show-sidebar")
    def show_sidebar(self) -> None:
        """Notify listeners that the main sidebar should be shown."""

    def set_loading(self, loading: bool) -> None:
        """Set whether or not to display a spinner."""
        self.sidebar_child_name = (
            "spinner" if loading and (not self.model.get_n_items()) else "content"
        )

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
