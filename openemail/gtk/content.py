# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from sys import platform
from typing import Any

from gi.repository import Adw, Gdk, GObject, Gtk

import openemail as app
from openemail import APP_ID, PREFIX, Notifier, Profile, Property

from .compose_sheet import ComposeSheet
from .contacts import Contacts
from .messages import Broadcasts, Drafts, Inbox, Outbox, Trash
from .navigation_row import NavigationRow
from .profile_settings import ProfileSettings

for t in Contacts, Broadcasts, Drafts, Inbox, Outbox, Trash:
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/content.ui")
class Content(Adw.BreakpointBin):
    """The main content of the application."""

    __gtype_name__ = "Content"

    compose_sheet: ComposeSheet = child
    split_view: Adw.OverlaySplitView = child

    sidebar_toolbar_view: Adw.ToolbarView = child
    sidebar: Gtk.ListBox = child
    stack: Adw.ViewStack = child
    profile_settings: ProfileSettings = child

    content_child_name = Property(str, default="inbox")
    profile_stack_child_name = Property(str, default="loading")
    profile_image = Property(Gdk.Paintable)
    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")

    @Property(str)
    def header_bar_layout(self) -> str:
        """The layout to use based on window controls."""
        if not platform.startswith("darwin"):
            layout = self.get_settings().props.gtk_decoration_layout
            if layout.replace("appmenu", "").startswith(":"):
                return "title"

        return "no-title"

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        ComposeSheet.default = self.compose_sheet

        self.sidebar.set_header_func(self._header_func)
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))

        Property.bind(Profile.of(app.user), "image", self, "profile-image")
        Property.bind(
            Notifier(), "sending", self.sidebar_toolbar_view, "reveal-bottom-bars"
        )

        self.get_settings().connect(
            "notify::gtk-decoration-layout",
            lambda *_: self.notify("header-bar-layout"),
        )

    def _header_func(self, row: NavigationRow, *_args):
        row.set_header(
            Gtk.Separator(
                margin_start=9,
                margin_end=9,
            )
            if row.separator
            else None
        )

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj, row: NavigationRow | None):
        if not row:
            return

        self.sidebar.select_row(row)
        self.stack.props.visible_child = row.page.props.child

        if self.split_view.props.collapsed:
            self.split_view.props.show_sidebar = False

    @Gtk.Template.Callback()
    def _on_profile_button_clicked(self, *_args):
        self.profile_settings.present(self)
