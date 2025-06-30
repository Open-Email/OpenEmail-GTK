# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from sys import platform
from typing import Any

from gi.repository import Adw, Gdk, GObject, Gtk

from openemail import APP_ID, PREFIX, Notifier, mail

from .contacts_page import ContactsPage
from .messages_page import BroadcastsPage, DraftsPage, InboxPage, OutboxPage, TrashPage
from .navigation_row import NavigationRow
from .profile_settings import ProfileSettings


@Gtk.Template.from_resource(f"{PREFIX}/gtk/content-view.ui")
class ContentView(Adw.BreakpointBin):
    """The main content of the application."""

    __gtype_name__ = "ContentView"

    split_view: Adw.OverlaySplitView = Gtk.Template.Child()

    sidebar_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    sidebar: Gtk.ListBox = Gtk.Template.Child()
    bottom_sidebar: Gtk.ListBox = Gtk.Template.Child()
    profile_settings: ProfileSettings = Gtk.Template.Child()

    inbox_page: InboxPage = Gtk.Template.Child()
    outbox_page: OutboxPage = Gtk.Template.Child()
    drafts_page: DraftsPage = Gtk.Template.Child()
    trash_page: TrashPage = Gtk.Template.Child()
    broadcasts_page: BroadcastsPage = Gtk.Template.Child()
    contacts_page: ContactsPage = Gtk.Template.Child()

    content_child_name = GObject.Property(type=str, default="inbox")
    profile_stack_child_name = GObject.Property(type=str, default="loading")
    profile_image = GObject.Property(type=Gdk.Paintable)
    app_icon_name = GObject.Property(type=str, default=f"{APP_ID}-symbolic")
    header_bar_layout = GObject.Property(
        type=str,
        default=(
            "no-title"
            if platform.startswith("darwin")
            or (
                (settings := Gtk.Settings.get_default())
                and not settings.props.gtk_decoration_layout.replace(
                    "appmenu", ""
                ).startswith(":")
            )
            else "title"
        ),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))

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

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: NavigationRow | None) -> None:
        if not row:
            return

        self.bottom_sidebar.unselect_all()
        self.sidebar.select_row(row)

        self.content_child_name = (
            "inbox",
            "outbox",
            "drafts",
            "trash",
        )[row.get_index()]

        if self.split_view.props.collapsed:
            self.split_view.props.show_sidebar = False

    @Gtk.Template.Callback()
    def _on_bottom_row_selected(self, _obj: Any, row: NavigationRow | None) -> None:
        if not row:
            return

        self.sidebar.unselect_all()
        self.bottom_sidebar.select_row(row)

        self.content_child_name = (
            "broadcasts",
            "contacts",
        )[row.get_index()]

        if self.split_view.props.collapsed:
            self.split_view.props.show_sidebar = False

    @Gtk.Template.Callback()
    def _on_profile_button_clicked(self, *_args: Any) -> None:
        self.profile_settings.present(self)
