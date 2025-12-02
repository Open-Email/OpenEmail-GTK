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
from openemail.gtk.contacts import ContactRow
from openemail.gtk.messages import MessageRow
from openemail.gtk.profile_view import ProfileView
from openemail.gtk.sidebar_item import FolderSidebarItem, SidebarItem
from openemail.store import DictStore, Folders, People, Profile

from .login_view import LoginView
from .profile_settings import ProfileSettings

for t in (
    ComposeSheet,
    ContactRow,
    MessageRow,
    ProfileView,
    DictStore,
    Folders,
    People,
):
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/window.ui")
class Window(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = __qualname__

    unread_filter: Gtk.Filter = child

    # For some reason, the badge doesn't update without these here
    inbox_unread: Gtk.FilterListModel = child
    trash_unread: Gtk.FilterListModel = child
    broadcasts_unread: Gtk.FilterListModel = child

    toast_overlay: Adw.ToastOverlay = child
    outer_split_view: Adw.OverlaySplitView = child

    sidebar_view: Adw.ToolbarView = child
    profile_settings: ProfileSettings = child

    sync_button: Gtk.Button = child
    offline_banner: Adw.Banner = child

    login_view: LoginView = child

    inner_sidebar: Adw.Sidebar = child  # pyright: ignore[reportAttributeAccessIssue]
    contacts_item: SidebarItem = child

    visible_child_name = Property(str, default="auth")
    profile_stack_child_name = Property(str, default="loading")
    item_type = Property(str, default="folder")

    item = Property(SidebarItem)
    folder = Property(FolderSidebarItem)

    search_text = Property(str)
    loading = Property(bool)

    profile_image = Property(Gdk.Paintable)
    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")

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
                lambda *_: self.outer_split_view.set_show_sidebar(
                    not self.outer_split_view.props.show_sidebar
                ),
            ),
        ))

        Property.bind(Profile.of(client.user), "image", self, "profile-image")
        Property.bind(app.notifier, "sending", self.sidebar_view, "reveal-bottom-bars")

        Property.bind_setting(store.state_settings, "width", self, "default-width")
        Property.bind_setting(store.state_settings, "height", self, "default-height")
        Property.bind_setting(
            store.state_settings,
            "show-sidebar",
            self.outer_split_view,
        )

        store.settings.connect(
            "changed::unread-messages",
            lambda *_: self.unread_filter.changed(Gtk.FilterChange.DIFFERENT),
        )

        self.get_settings().connect(
            "notify::gtk-decoration-layout",
            lambda *_: self.notify("header-bar-layout"),
        )

        def on_syncing_changed(*_args):
            if app.notifier.syncing:
                self.sync_button.props.sensitive = False
                self.sync_button.add_css_class("spinning")
            else:
                self.sync_button.remove_css_class("spinning")
                self.sync_button.props.sensitive = True

        app.notifier.connect("notify::syncing", on_syncing_changed)
        app.notifier.connect("send", self._on_send_notification)
        Property.bind(app.notifier, "offline", self.offline_banner, "revealed")

        tasks.create(store.sync(periodic=True))

        self._switch_page(None, 0)

        if client.user.logged_in:
            self.visible_child_name = "content"

    def _on_send_notification(self, _obj, toast: Adw.Toast):
        if isinstance(dialog := self.props.visible_dialog, Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.add_toast(toast)

    @Gtk.Template.Callback()
    def _switch_page(self, _obj, index: int):  # pyright: ignore[reportAttributeAccessIssue]
        self.item = self.inner_sidebar.get_item(index)  # pyright: ignore[reportUnknownVariableType]

        match self.item:
            case FolderSidebarItem():
                self.folder = self.item
                self.item_type = "folder"
            case self.contacts_item:
                self.item_type = "contacts"

        if self.outer_split_view.props.collapsed:
            self.outer_split_view.props.show_sidebar = False

    @Gtk.Template.Callback()
    def _on_auth(self, *_args):
        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _sync(self, *_args):
        tasks.create(store.sync())

    @Gtk.Template.Callback()
    def _get_list_child_name(
        self,
        _obj,
        item_type: str,
        folder_n_items: int,
        contacts_n_items: int,
        loading: bool,
        search_text: str,
    ) -> str:
        return (
            item_type
            if (
                folder_n_items
                if item_type == "folder"
                else contacts_n_items
                if item_type == "contacts"
                else 0
            )
            else "loading"
            if loading
            else "no-results"
            if search_text
            else "empty"
        )
