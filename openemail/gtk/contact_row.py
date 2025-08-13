# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo


from gi.repository import GObject, Gtk

import openemail as app
from openemail import PREFIX, Profile, settings


@Gtk.Template.from_resource(f"{PREFIX}/contact-row.ui")
class ContactRow(Gtk.Box):
    """A row to display a contact or contact request."""

    __gtype_name__ = "ContactRow"

    profile = GObject.Property(type=Profile)

    @Gtk.Template.Callback()
    def _accept(self, *_args):
        self._remove_address()

        try:
            app.create_task(app.address_book.new(self.profile.value_of("address")))
        except ValueError:
            return

    @Gtk.Template.Callback()
    def _decline(self, *_args):
        self._remove_address()

    def _remove_address(self):
        try:
            (requests := settings.get_strv("contact-requests")).remove(
                self.profile.value_of("address")
            )
        except ValueError:
            return

        settings.set_strv("contact-requests", requests)
