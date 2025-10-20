# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
from typing import Any

import keyring
from gi.repository import Adw, Gio, Gtk

from openemail import APP_ID, PREFIX, Notifier, Property, store, tasks
from openemail.core import client

from .content import Content
from .login_view import LoginView

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/window.ui")
class Window(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = __qualname__

    toast_overlay: Adw.ToastOverlay = child

    login_view: LoginView = child
    content: Content = child

    visible_child_name = Property(str, default="auth")

    _quit: bool = False

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        store.state_settings.bind(
            "width",
            self,
            "default-width",
            Gio.SettingsBindFlags.DEFAULT,
        )
        store.state_settings.bind(
            "height",
            self,
            "default-height",
            Gio.SettingsBindFlags.DEFAULT,
        )
        store.state_settings.bind(
            "show-sidebar",
            self.content.split_view,
            "show-sidebar",
            Gio.SettingsBindFlags.DEFAULT,
        )

        Notifier().connect("send", self._on_send_notification)
        tasks.create(store.sync(periodic=True))

        if not client.user.logged_in:
            return

        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _on_auth(self, *_args):
        keyring.set_password(
            f"{APP_ID}.Keys",
            client.user.address,
            json.dumps(
                {
                    "privateEncryptionKey": str(client.user.encryption_keys.private),
                    "privateSigningKey": str(client.user.signing_keys),
                }
            ),
        )

        store.settings.set_string("address", client.user.address)

        tasks.create(store.sync())
        self.visible_child_name = "content"

    def _on_send_notification(self, _obj, toast: Adw.Toast):
        if isinstance(dialog := self.props.visible_dialog, Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.add_toast(toast)
