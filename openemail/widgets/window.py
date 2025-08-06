# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
from typing import Any

import keyring
from gi.repository import Adw, Gio, GObject, Gtk

from openemail import app
from openemail.app import APP_ID, PREFIX, Notifier, store
from openemail.app.store import settings, state_settings
from openemail.core import client

from .content import Content
from .login_view import LoginView


@Gtk.Template.from_resource(f"{PREFIX}/window.ui")
class Window(Adw.ApplicationWindow):
    """The main application window."""

    __gtype_name__ = "Window"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()

    login_view: LoginView = Gtk.Template.Child()
    content: Content = Gtk.Template.Child()

    visible_child_name = GObject.Property(type=str, default="auth")

    _quit: bool = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        state_settings.bind(
            "width",
            self,
            "default-width",
            Gio.SettingsBindFlags.DEFAULT,
        )
        state_settings.bind(
            "height",
            self,
            "default-height",
            Gio.SettingsBindFlags.DEFAULT,
        )
        state_settings.bind(
            "show-sidebar",
            self.content.split_view,
            "show-sidebar",
            Gio.SettingsBindFlags.DEFAULT,
        )

        Notifier().connect("send", self._on_send_notification)
        app.create_task(store.sync(periodic=True))

        if not client.user.logged_in:
            return

        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _on_auth(self, *_args: Any) -> None:
        keyring.set_password(
            f"{APP_ID}.Keys",
            str(client.user.address),
            json.dumps(
                {
                    "privateEncryptionKey": str(client.user.encryption_keys.private),
                    "privateSigningKey": str(client.user.signing_keys),
                }
            ),
        )

        settings.set_string("address", str(client.user.address))

        app.create_task(store.sync())
        self.visible_child_name = "content"

    def _on_send_notification(self, _obj: Any, toast: Adw.Toast) -> None:
        if isinstance(dialog := self.props.visible_dialog, Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.add_toast(toast)
