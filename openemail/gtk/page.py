# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import TYPE_CHECKING, Any, cast

from gi.repository import Adw, Gtk

from openemail import PREFIX, Notifier, Property, store, tasks

if TYPE_CHECKING:
    from .window import Window


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/page.ui")
class Page(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "Page"

    split_view: Adw.NavigationSplitView = child
    sync_button: Gtk.Button = child
    offline_banner: Adw.Banner = child

    factory = Property(Gtk.ListItemFactory)

    sidebar_child_name = Property(str, default="empty")
    search_text = Property(str)

    title = Property(str, default=_("Content"))
    subtitle = Property(str)
    details = Property(Gtk.Widget)
    toolbar_button = Property(Gtk.Widget)
    empty_page = Property(Gtk.Widget)

    model = Property(Gtk.SingleSelection)
    loading = Property(bool)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        def on_syncing_changed(*_args):
            if Notifier().syncing:
                self.sync_button.props.sensitive = False
                self.sync_button.add_css_class("spinning")
            else:
                self.sync_button.remove_css_class("spinning")
                self.sync_button.props.sensitive = True

        Notifier().connect("notify::syncing", on_syncing_changed)
        Property.bind(Notifier(), "offline", self.offline_banner, "revealed")

    @Gtk.Template.Callback()
    def _show_sidebar(self, *_args):
        split_view = cast("Window", self.props.root).content.split_view
        split_view.props.show_sidebar = not split_view.props.show_sidebar

    @Gtk.Template.Callback()
    def _sync(self, *_args):
        tasks.create(store.sync())

    @Gtk.Template.Callback()
    def _get_sidebar_child_name(
        self, _obj, items: int, loading: bool, search_text: str
    ) -> str:
        return (
            "content"
            if items
            else "loading"
            if loading
            else "no-results"
            if search_text
            else "empty"
        )
