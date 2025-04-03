# contacts_page.py
#
# Authors: kramo
# Copyright 2025 Mercata Sagl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from locale import strcoll
from typing import Any

from gi.repository import Adw, Gtk

from openemail.core.network import new_contact
from openemail.core.user import Address
from openemail.shared import PREFIX, run_task, user
from openemail.store import MailProfile, address_book, broadcasts, inbox
from openemail.widgets.form import MailForm

from .content_page import MailContentPage
from .profile_view import MailProfileView


@Gtk.Template(resource_path=f"{PREFIX}/gtk/contacts-page.ui")
class MailContactsPage(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "MailContactsPage"

    content: MailContentPage = Gtk.Template.Child()
    profile_view: MailProfileView = Gtk.Template.Child()

    add_contact_dialog: Adw.AlertDialog = Gtk.Template.Child()
    address: Adw.EntryRow = Gtk.Template.Child()
    address_form: MailForm = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.content.model = (
            selection := Gtk.SingleSelection(
                autoselect=False,
                model=Gtk.SortListModel.new(
                    Gtk.FilterListModel.new(
                        address_book,
                        (
                            filter := Gtk.CustomFilter.new(
                                lambda item: (
                                    (lowered := self.content.search_text.lower())
                                    in item.address.lower()
                                    or lowered in item.name.lower()
                                )
                                if self.content.search_text
                                else True
                            )
                        ),
                    ),
                    Gtk.CustomSorter.new(lambda a, b, _: strcoll(a.name, b.name)),
                ),
            )
        )

        self.content.connect(
            "notify::search-text",
            lambda *_: filter.changed(
                Gtk.FilterChange.DIFFERENT,
            ),
        )

        selection.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/gtk/contact-row.ui"
        )

        self.add_controller(
            controller := Gtk.ShortcutController(
                scope=Gtk.ShortcutScope.GLOBAL,
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>n"),
                Gtk.CallbackAction.new(lambda *_: not (self._new_contact())),
            )
        )

    @Gtk.Template.Callback()
    def _new_contact(self, *_args: Any) -> None:
        self.address_form.reset()
        self.add_contact_dialog.present(self)

    @Gtk.Template.Callback()
    def _add_contact(self, _obj: Any, response: str) -> None:
        if response != "add":
            return

        try:
            address = Address(self.address.get_text())
        except ValueError:
            return

        def update_address_book_cb() -> None:
            run_task(broadcasts.update())
            run_task(inbox.update())

        run_task(
            new_contact(address, user),
            lambda: run_task(
                address_book.update(),
                update_address_book_cb,
            ),
        )

        self.add_contact_dialog.force_close()

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not isinstance(selected := selection.get_selected_item(), MailProfile):
            return

        self.profile_view.profile = selected.profile
        self.profile_view.profile_image = selected.image

        self.content.split_view.set_show_content(True)
