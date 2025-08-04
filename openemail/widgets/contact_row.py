# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import GObject, Gtk

from openemail.app import PREFIX, create_task, mail
from openemail.app.mail import Profile
from openemail.app.store import settings


@Gtk.Template.from_resource(f"{PREFIX}/contact-row.ui")
class ContactRow(Gtk.Box):
    """A row to display a contact or contact request."""

    __gtype_name__ = "ContactRow"

    profile = GObject.Property(type=Profile)

    @Gtk.Template.Callback()
    def _accept(self, *_args: Any) -> None:
        self._remove_address()

        try:
            create_task(mail.address_book.new(self.profile.value_of("address")))
        except ValueError:
            return

    @Gtk.Template.Callback()
    def _decline(self, *_args: Any) -> None:
        self._remove_address()

    def _remove_address(self) -> None:
        try:
            (requests := settings.get_strv("contact-requests")).remove(
                self.profile.value_of("address")
            )
        except ValueError:
            return

        settings.set_strv("contact-requests", requests)
