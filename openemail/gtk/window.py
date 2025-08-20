# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
from typing import Any

import keyring
from gi.repository import Adw, Gio, GObject, Gtk

import openemail as app
from openemail import APP_ID, PREFIX, Notifier

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

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        app.state_settings.bind(
            "width",
            self,
            "default-width",
            Gio.SettingsBindFlags.DEFAULT,
        )
        app.state_settings.bind(
            "height",
            self,
            "default-height",
            Gio.SettingsBindFlags.DEFAULT,
        )
        app.state_settings.bind(
            "show-sidebar",
            self.content.split_view,
            "show-sidebar",
            Gio.SettingsBindFlags.DEFAULT,
        )

        Notifier().connect("send", self._on_send_notification)
        app.create_task(app.sync(periodic=True))

        if not app.user.logged_in:
            return

        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _on_auth(self, *_args):
        keyring.set_password(
            f"{APP_ID}.Keys",
            app.user.address,
            json.dumps(
                {
                    "privateEncryptionKey": str(app.user.encryption_keys.private),
                    "privateSigningKey": str(app.user.signing_keys),
                }
            ),
        )

        app.settings.set_string("address", app.user.address)

        app.create_task(app.sync())
        self.visible_child_name = "content"

    def _on_send_notification(self, _obj, toast: Adw.Toast):
        if isinstance(dialog := self.props.visible_dialog, Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.add_toast(toast)
