# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX, create_task, mail
from openemail.mail import Address

from .contact_row import ContactRow  # noqa: F401
from .form import Form
from .page import Page
from .profile_view import ProfileView


@Gtk.Template.from_resource(f"{PREFIX}/contacts.ui")
class Contacts(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "Contacts"

    content: Page = Gtk.Template.Child()
    profile_view: ProfileView = Gtk.Template.Child()

    add_contact_dialog: Adw.AlertDialog = Gtk.Template.Child()
    address: Adw.EntryRow = Gtk.Template.Child()
    address_form: Form = Gtk.Template.Child()

    models: Gio.ListStore = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.models.append(mail.contact_requests)
        self.models.append(mail.address_book)

        mail.address_book.bind_property(
            "updating",
            self.content,
            "loading",
            GObject.BindingFlags.SYNC_CREATE,
        )

    @Gtk.Template.Callback()
    def _new_contact(self, *_args: Any) -> None:
        self.address_form.reset()
        self.add_contact_dialog.present(self)

    @Gtk.Template.Callback()
    def _add_contact(self, *_args: Any) -> None:
        try:
            create_task(mail.address_book.new(Address(self.address.props.text)))
        except ValueError:
            return

    @Gtk.Template.Callback()
    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        self.content.split_view.props.show_content = bool(selection.props.selected_item)
