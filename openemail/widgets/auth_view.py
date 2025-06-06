# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, GLib, GObject, Gtk

from openemail import APP_ID, PREFIX, Notifier, mail
from openemail.mail import Address, KeyPair

from .form import Form


@Gtk.Template.from_resource(f"{PREFIX}/gtk/auth-view.ui")
class AuthView(Adw.Bin):
    """A view prompting the user to log in."""

    __gtype_name__ = "AuthView"

    navigation_view: Adw.NavigationView = Gtk.Template.Child()

    email_status_page: Adw.StatusPage = Gtk.Template.Child()
    email_entry: Adw.EntryRow = Gtk.Template.Child()
    email_form: Form = Gtk.Template.Child()

    user_name_entry: Adw.EntryRow = Gtk.Template.Child()
    register_form: Form = Gtk.Template.Child()

    signing_key_entry: Adw.EntryRow = Gtk.Template.Child()
    encryption_key_entry: Adw.EntryRow = Gtk.Template.Child()
    auth_form: Form = Gtk.Template.Child()

    button_child_name = GObject.Property(type=str, default="label")
    register_button_child_name = GObject.Property(type=str, default="label")

    authenticated = GObject.Signal()

    def __init__(self, **_kwargs: Any) -> None:
        self.email_status_page.props.icon_name = APP_ID

    @Gtk.Template.Callback()
    def _log_in(self, *_args: Any) -> None:
        if self.email_form.invalid:
            return

        self.navigation_view.push_by_tag("keys")
        self.signing_key_entry.grab_focus()

    @Gtk.Template.Callback()
    def _sign_up(self, *_args: Any) -> None:
        self.navigation_view.push_by_tag("sign-up")

    @Gtk.Template.Callback()
    def _register(self, *_args: Any) -> None:
        try:
            mail.user.address = Address(self.user_name_entry.props.text + "@open.email")
        except ValueError:
            Notifier.send(_("Invalid name, try another one"))
            return

        mail.user.encryption_keys = KeyPair.for_encryption()
        mail.user.signing_keys = KeyPair.for_signing()

        def success() -> None:
            self.register_button_child_name = "label"
            self.emit("authenticated")

            def reset() -> None:
                self.email_form.reset()
                self.register_form.reset()
                self.navigation_view.pop_to_tag("landing")
                self.auth_form.reset()

            GLib.timeout_add_seconds(1, reset)

        self.register_button_child_name = "loading"
        mail.register(
            success,
            lambda: self.set_property(
                "register-button-child-name",
                "label",
            ),
        )

    @Gtk.Template.Callback()
    def _focus_encryption_key_entry(self, *_args: Any) -> None:
        self.encryption_key_entry.grab_focus()

    @Gtk.Template.Callback()
    def _authenticate(self, *_args: Any) -> None:
        if self.auth_form.invalid:
            return

        try:
            mail.user.address = Address(self.email_entry.props.text)
            mail.user.encryption_keys = KeyPair.from_b64(
                self.encryption_key_entry.props.text,
            )
            mail.user.signing_keys = KeyPair.from_b64(
                self.signing_key_entry.props.text,
            )

        except ValueError:
            Notifier.send(_("Incorrect key format"))
            return

        def success() -> None:
            self.button_child_name = "label"
            self.emit("authenticated")

            def reset() -> None:
                self.email_form.reset()
                self.register_form.reset()
                self.navigation_view.pop_to_tag("landing")
                self.auth_form.reset()

            GLib.timeout_add_seconds(1, reset)

        self.button_child_name = "loading"
        mail.try_auth(
            success,
            lambda: self.set_property(
                "button-child-name",
                "label",
            ),
        )
