# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, Notifier, mail, create_task


@Gtk.Template.from_resource(f"{PREFIX}/page.ui")
class Page(Adw.BreakpointBin):
    """A split view for content and details."""

    __gtype_name__ = "Page"

    split_view: Adw.NavigationSplitView = Gtk.Template.Child()
    sync_button: Gtk.Button = Gtk.Template.Child()

    factory = GObject.Property(type=Gtk.ListItemFactory)

    sidebar_child_name = GObject.Property(type=str, default="empty")
    search_text = GObject.Property(type=str)

    title = GObject.Property(type=str, default=_("Content"))
    details = GObject.Property(type=Gtk.Widget)
    toolbar_button = GObject.Property(type=Gtk.Widget)
    empty_page = GObject.Property(type=Gtk.Widget)

    model = GObject.Property(type=Gtk.SingleSelection)
    loading = GObject.Property(type=bool, default=False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        def on_syncing_changed(*_args: Any) -> None:
            if Notifier().syncing:
                self.sync_button.props.sensitive = False
                self.sync_button.add_css_class("spinning")
                return

            self.sync_button.remove_css_class("spinning")
            self.sync_button.props.sensitive = True

        Notifier().connect("notify::syncing", on_syncing_changed)

    @Gtk.Template.Callback()
    def _show_sidebar(self, *_args: Any) -> None:
        if not isinstance(
            split_view := getattr(
                getattr(self.props.root, "content", None),
                "split_view",
                None,
            ),
            Adw.OverlaySplitView,
        ):
            return

        split_view.props.show_sidebar = not split_view.props.show_sidebar

    @Gtk.Template.Callback()
    def _sync(self, *_args: Any) -> None:
        create_task(mail.sync())

    @Gtk.Template.Callback()
    def _get_sidebar_child_name(
        self, _obj: Any, items: int, loading: bool, search_text: str
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
