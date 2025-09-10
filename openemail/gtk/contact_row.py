# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo


from contextlib import suppress

from gi.repository import Gtk

from openemail import PREFIX, Property, store, tasks
from openemail.profile import Profile


@Gtk.Template.from_resource(f"{PREFIX}/contact-row.ui")
class ContactRow(Gtk.Box):
    """A row to display a contact or contact request."""

    __gtype_name__ = "ContactRow"

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
