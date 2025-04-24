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

from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX


@Gtk.Template(resource_path=f"{PREFIX}/gtk/content-page.ui")
class MailContentPage(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "MailContentPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    search_bar: Gtk.SearchBar = Gtk.Template.Child()

    factory = GObject.Property(type=Gtk.ListItemFactory)

    sidebar_child_name = GObject.Property(type=str, default="empty")
    search_text = GObject.Property(type=str)

    title = GObject.Property(type=str, default=_("Content"))
    details = GObject.Property(type=Gtk.Widget)
    toolbar_button = GObject.Property(type=Gtk.Widget)
    empty_page = GObject.Property(type=Gtk.Widget)

    _model: Gtk.SelectionModel | None = None
    _loading: bool = False

    @GObject.Property(type=bool, default=False)
    def loading(self) -> bool:
        """Get whether or not to display a loading indicator in case the page is empty."""
        return self._loading

    @loading.setter
    def loading(self, loading: bool) -> None:
        self._loading = loading
        self._update_stack()

    @GObject.Property(type=Gtk.SelectionModel)
    def model(self) -> Gtk.SelectionModel | None:
        """Get the selection model."""
        return self._model

    @model.setter
    def model(self, model: Gtk.SelectionModel) -> None:
        if self._model:
            self._model.disconnect_by_func(self._update_stack)

        self._model = model

        model.connect("items-changed", self._update_stack)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.add_controller(
            controller := Gtk.ShortcutController(
                scope=Gtk.ShortcutScope.GLOBAL,
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>f"),
                Gtk.CallbackAction.new(
                    lambda *_: not (
                        self.search_bar.set_search_mode(
                            not self.search_bar.props.search_mode_enabled,
                        )
                    )
                ),
            )
        )

        self.connect(
            "realize",
            lambda *_: self.search_bar.set_key_capture_widget(root)
            if isinstance(root := self.props.root, Gtk.Widget)
            else None,
        )

    @Gtk.Template.Callback()
    def _show_sidebar(self, *_args: Any) -> None:
        if not isinstance(
            split_view := getattr(
                getattr(self.props.root, "content_view", None),
                "split_view",
                None,
            ),
            Adw.OverlaySplitView,
        ):
            return

        split_view.props.show_sidebar = not split_view.props.show_sidebar

    def _update_stack(self, *_args: Any) -> None:
        self.sidebar_child_name = (
            "content"
            if self.model.get_n_items()
            else "loading"
            if self._loading
            else "no-results"
            if self.search_text
            else "empty"
        )
