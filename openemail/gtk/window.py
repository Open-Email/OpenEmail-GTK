# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo


from sys import platform
from typing import Any

from gi.repository import Adw, Gdk, GObject, Gtk

import openemail as app
from openemail import APP_ID, PREFIX, Property, store, tasks
from openemail.core import client
from openemail.gtk.compose_sheet import ComposeSheet
from openemail.store import Profile

from .contacts import Contacts
from .login_view import LoginView
from .messages import Broadcasts, Drafts, Inbox, Outbox, Sent, Trash
from .profile_settings import ProfileSettings

for t in Contacts, Broadcasts, Drafts, Inbox, Outbox, Sent, Trash, ComposeSheet:
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/window.ui")
class Window(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = __qualname__

    toast_overlay: Adw.ToastOverlay = child
    split_view: Adw.OverlaySplitView = child

    sidebar_view: Adw.ToolbarView = child
    stack: Adw.ViewStack = child
    profile_settings: ProfileSettings = child

    content_child_name = Property(str, default="inbox")
    profile_stack_child_name = Property(str, default="loading")
    profile_image = Property(Gdk.Paintable)
    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")

    login_view: LoginView = child

    visible_child_name = Property(str, default="auth")

    _quit: bool = False

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

        self.add_action_entries((
            ("profile-settings", lambda *_: self.profile_settings.present(self)),
            (
                "toggle-sidebar",
                lambda *_: self.split_view.set_show_sidebar(
                    not self.split_view.props.show_sidebar
                ),
            ),
        ))

        Property.bind(Profile.of(client.user), "image", self, "profile-image")
        Property.bind(app.notifier, "sending", self.sidebar_view, "reveal-bottom-bars")

        Property.bind_setting(store.state_settings, "width", self, "default-width")
        Property.bind_setting(store.state_settings, "height", self, "default-height")
        Property.bind_setting(store.state_settings, "show-sidebar", self.split_view)

        self.get_settings().connect(
            "notify::gtk-decoration-layout",
            lambda *_: self.notify("header-bar-layout"),
        )

        app.notifier.connect("send", self._on_send_notification)
        tasks.create(store.sync(periodic=True))

        if client.user.logged_in:
            self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _hide_sidebar(self, *_args):
        if self.split_view.props.collapsed:
            self.split_view.props.show_sidebar = False

    @Gtk.Template.Callback()
    def _on_auth(self, *_args):
        self.visible_child_name = "content"

    def _on_send_notification(self, _obj, toast: Adw.Toast):
        if isinstance(dialog := self.props.visible_dialog, Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.add_toast(toast)
