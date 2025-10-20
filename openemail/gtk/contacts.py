# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from contextlib import suppress

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, Property, store, tasks
from openemail.core.model import Address
from openemail.store import DictStore, People

from .contact_row import ContactRow
from .form import Form
from .page import Page
from .profile_view import ProfileView

for t in DictStore, People, ContactRow, ProfileView:
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/contacts.ui")
class Contacts(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "Contacts"

    page: Page = child

    add_contact_dialog: Adw.AlertDialog = child
    address: Adw.EntryRow = child
    address_form: Form = child

    counter = Property(int)

    @Gtk.Template.Callback()
    def _new_contact(self, *_args):
        self.address_form.reset()
        self.add_contact_dialog.present(self)

    @Gtk.Template.Callback()
    def _add_contact(self, *_args):
        with suppress(ValueError):
            tasks.create(store.address_book.new(Address(self.address.props.text)))

    @Gtk.Template.Callback()
    def _on_selected(self, selection: Gtk.SingleSelection, *_args):
        self.page.split_view.props.show_content = bool(selection.props.selected_item)
