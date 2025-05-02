# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import GObject, Gtk

from openemail import PREFIX, mail, run_task, settings
from openemail.mail import Address


@Gtk.Template(resource_path=f"{PREFIX}/gtk/request-buttons.ui")
class RequestButtons(Gtk.Box):
    """Buttons to accept or decline a contact request."""

    __gtype_name__ = "RequestButtons"

    address = GObject.Property(type=str)

    @Gtk.Template.Callback()
    def _accept(self, *_args: Any) -> None:
        self._remove_address()

        try:
            run_task(mail.address_book.new(Address(self.address)))
        except ValueError:
            return

    @Gtk.Template.Callback()
    def _decline(self, *_args: Any) -> None:
        self._remove_address()

    def _remove_address(self) -> None:
        try:
            (requests := settings.get_strv("contact-requests")).remove(self.address)
        except ValueError:
            return

        settings.set_strv("contact-requests", requests)
