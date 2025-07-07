# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import json
from collections.abc import Callable, Sequence
from typing import Any

import keyring
from gi.repository import Adw, Gio, GObject, Gtk

from openemail import (
    APP_ID,
    PREFIX,
    Notifier,
    log_file,
    mail,
    run_task,
    settings,
    state_settings,
)

from .content import Content
from .login_view import LoginView
from .preferences import Preferences


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

        self._create_action(
            "preferences", lambda *_: self._present_preferences(), ("<primary>comma",)
        )
        self._create_action("about", lambda *_: self._present_about_dialog())
        self._create_action("quit", lambda *_: self.close(), ("<primary>q",))

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

        if not mail.user.logged_in:
            return

        self.visible_child_name = "content"

    @Gtk.Template.Callback()
    def _on_auth(self, *_args: Any) -> None:
        keyring.set_password(
            f"{APP_ID}.Keys",
            str(mail.user.address),
            json.dumps(
                {
                    "privateEncryptionKey": str(mail.user.encryption_keys.private),
                    "privateSigningKey": str(mail.user.signing_keys),
                }
            ),
        )

        settings.set_string("address", str(mail.user.address))

        run_task(mail.sync())
        self.visible_child_name = "content"

    def _on_send_notification(self, _obj: Any, toast: Adw.Toast) -> None:
        if isinstance(dialog := self.props.visible_dialog, Adw.PreferencesDialog):
            dialog.add_toast(toast)
            return

        self.toast_overlay.add_toast(toast)

    def _present_preferences(self) -> None:
        preferences = Preferences()
        preferences.connect(
            "logged-out", lambda *_: self.set_property("visible-child-name", "auth")
        )
        preferences.present(self)

    def _present_about_dialog(self) -> None:
        about = Adw.AboutDialog.new_from_appdata(f"{PREFIX}/{APP_ID}.metainfo.xml")
        about.props.developers = ["kramo https://kramo.page"]
        about.props.designers = [
            "kramo https://kramo.page",
            "Varti Studio https://varti-studio.com",
        ]
        about.props.copyright = "© 2025 Mercata Sagl"
        # Translators: Replace "translator-credits" with your name/username,
        # and optionally an email or URL.
        about.props.translator_credits = _("translator-credits")

        try:
            about.props.debug_info = log_file.read_text()
        except FileNotFoundError:
            pass
        else:
            about.props.debug_info_filename = log_file.name

        about.present(self)

    def _create_action(
        self,
        name: str,
        callback: Callable[..., Any],
        shortcuts: Sequence[str] | None = None,
    ) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts and (app := self.props.application):
            app.set_accels_for_action(f"win.{name}", shortcuts)
