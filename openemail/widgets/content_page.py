# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX


@Gtk.Template(resource_path=f"{PREFIX}/gtk/content-page.ui")
class MailContentPage(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "MailContentPage"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()

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
