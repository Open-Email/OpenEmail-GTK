# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo


from contextlib import suppress

from gi.repository import Gtk

import openemail as app
from openemail import PREFIX, Profile, Property


@Gtk.Template.from_resource(f"{PREFIX}/contact-row.ui")
class ContactRow(Gtk.Box):
    """A row to display a contact or contact request."""

    __gtype_name__ = "ContactRow"

    profile = Property(Profile)

    @Gtk.Template.Callback()
    def _accept(self, *_args):
        address = self.profile.value_of("address")
        app.settings_discard("contact-requests", address)

        with suppress(ValueError):
            app.create_task(app.address_book.new(address))

    @Gtk.Template.Callback()
    def _decline(self, *_args):
        app.settings_discard("contact-requests", self.profile.value_of("address"))
