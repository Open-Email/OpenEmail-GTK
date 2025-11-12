# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from contextlib import suppress

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, Property, store, tasks
from openemail.core.model import Address
from openemail.profile import Profile
from openemail.store import DictStore, People

from .form import Form
from .page import Page
from .profile_view import ProfileView

for t in DictStore, People, ProfileView:
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/contact-row.ui")
class ContactRow(Gtk.Box):
    """A row to display a contact or contact request."""

    __gtype_name__ = __qualname__

    profile = Property(Profile)

    @Gtk.Template.Callback()
    def _accept(self, *_args):
        address = self.profile.value_of("address")
        store.settings_discard("contact-requests", address)

        with suppress(ValueError):
            tasks.create(store.address_book.new(address))

    @Gtk.Template.Callback()
    def _decline(self, *_args):
        store.settings_discard("contact-requests", self.profile.value_of("address"))


@Gtk.Template.from_resource(f"{PREFIX}/contacts.ui")
class Contacts(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = __qualname__

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
