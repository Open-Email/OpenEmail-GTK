# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from sys import platform
from typing import Any

from gi.repository import Adw, Gdk, GObject, Gtk

from openemail import APP_ID, PREFIX, Notifier, mail

from .contacts import Contacts  # noqa: F401
from .messages import Broadcasts, Drafts, Inbox, Outbox, Trash  # noqa: F401
from .navigation_row import NavigationRow
from .profile_settings import ProfileSettings

SECOND_SIDEBAR_GROUP_INDEX = 4


@Gtk.Template.from_resource(f"{PREFIX}/content.ui")
class Content(Adw.BreakpointBin):
    """The main content of the application."""

    __gtype_name__ = "Content"

    split_view: Adw.OverlaySplitView = Gtk.Template.Child()

    sidebar_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()
    content: Adw.ViewStack = Gtk.Template.Child()

    content_child_name = GObject.Property(type=str, default="inbox")
    profile_stack_child_name = GObject.Property(type=str, default="loading")
    profile_image = GObject.Property(type=Gdk.Paintable)
    app_icon_name = GObject.Property(type=str, default=f"{APP_ID}-symbolic")

    @GObject.Property(type=str)
    def header_bar_layout(self) -> str:
        """Get the header bar layout."""
        layout = (
            settings.props.gtk_decoration_layout
            if (settings := Gtk.Settings.get_default())
            else "appmenu:close"  # GNOME default
        )

        is_mac = platform.startswith("darwin")
        has_start_window_controls = not layout.replace("appmenu", "").startswith(":")

        return "no-title" if is_mac or has_start_window_controls else "title"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        Notifier().bind_property(
            "sending",
            self.sidebar_toolbar_view,
            "reveal-bottom-bars",
            GObject.BindingFlags.SYNC_CREATE,
        )

        mail.user_profile.bind_property(
            "image",
            self,
            "profile-image",
            GObject.BindingFlags.SYNC_CREATE,
        )

        self.sidebar.select_row(self.sidebar.get_row_at_index(0))
        self.sidebar.set_header_func(self._header_func)

    def _header_func(self, row: Gtk.ListBoxRow, *_args: Any) -> None:
        if row.get_index() == SECOND_SIDEBAR_GROUP_INDEX:
            row.set_header(Gtk.Separator())

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: NavigationRow) -> None:
        self.sidebar.select_row(row)
        self.content.props.visible_child = row.page.props.child
        self.split_view.props.show_sidebar = not self.split_view.props.collapsed

    @Gtk.Template.Callback()
    def _present_profile_settings(self, dialog: ProfileSettings, *_args: Any) -> None:
        dialog.present(self)
