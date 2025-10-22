# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from sys import platform
from typing import Any

from gi.repository import Adw, Gdk, Gio, GObject, Gtk

from openemail import APP_ID, PREFIX, Notifier, Property
from openemail.core import client
from openemail.gtk.compose_sheet import ComposeSheet
from openemail.store import Profile

from .contacts import Contacts
from .messages import Broadcasts, Drafts, Inbox, Outbox, Sent, Trash
from .profile_settings import ProfileSettings

for t in Contacts, Broadcasts, Drafts, Inbox, Outbox, Sent, Trash, ComposeSheet:
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/content.ui")
class Content(Adw.BreakpointBin):
    """The main content of the application."""

    __gtype_name__ = __qualname__

    split_view: Adw.OverlaySplitView = child

    sidebar_toolbar_view: Adw.ToolbarView = child
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

        self.insert_action_group("content", group := Gio.SimpleActionGroup())
        group.add_action_entries(
            (
                ("profile-settings", lambda *_: self.profile_settings.present(self)),
                (
                    "toggle-sidebar",
                    lambda *_: self.split_view.set_show_sidebar(
                        not self.split_view.props.show_sidebar
                    ),
                ),
            ),
        )

        Property.bind(Profile.of(client.user), "image", self, "profile-image")
        Property.bind(
            Notifier(), "sending", self.sidebar_toolbar_view, "reveal-bottom-bars"
        )

        self.get_settings().connect(
            "notify::gtk-decoration-layout",
            lambda *_: self.notify("header-bar-layout"),
        )

    @Gtk.Template.Callback()
    def _hide_sidebar(self, *_args):
        if self.split_view.props.collapsed:
            self.split_view.props.show_sidebar = False
