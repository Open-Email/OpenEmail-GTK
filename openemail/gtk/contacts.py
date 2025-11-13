# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from openemail import PREFIX, Property, store, tasks
from openemail.core.model import Address
from openemail.profile import Profile
from openemail.store import DictStore, People

from .form import Form
from .page import Page
from .profile_view import ProfileView

if TYPE_CHECKING:
    from collections.abc import Awaitable

for t in DictStore, People, ProfileView:
    GObject.type_ensure(t)


child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/contact-row.ui")
class ContactRow(Gtk.Box):
    """A row to display a contact or contact request."""

    __gtype_name__ = __qualname__

    profile = Property(Profile)

    context_menu: Gtk.PopoverMenu = child

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("row", group := Gio.SimpleActionGroup())
        group.add_action_entries(
            (
                (
                    "remove",
                    lambda *_: self.activate_action(
                        "contacts.remove", GLib.Variant.new_string(self.profile.address)
                    ),
                ),
            )
        )

    @Gtk.Template.Callback()
    def _accept(self, *_args):
        address = self.profile.value_of("address")
        store.settings_discard("contact-requests", address)

        with suppress(ValueError):
            tasks.create(store.address_book.new(address))

    @Gtk.Template.Callback()
    def _decline(self, *_args):
        store.settings_discard("contact-requests", self.profile.value_of("address"))

    @Gtk.Template.Callback()
    def _show_context_menu(self, _gesture, _n_press: int, x: float, y: float):
        if self.profile.contact_request:
            return

        rect = Gdk.Rectangle()
        rect.x, rect.y = int(x), int(y)
        self.context_menu.props.pointing_to = rect
        self.context_menu.popup()


@Gtk.Template.from_resource(f"{PREFIX}/contacts.ui")
class Contacts(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = __qualname__

    page: Page = child

    add_contact_dialog: Adw.AlertDialog = child
    remove_contact_dialog: Adw.AlertDialog = child
    address: Adw.EntryRow = child
    address_form: Form = child

    counter = Property(int)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("contacts", group := Gio.SimpleActionGroup())
        group.add_action_entries(
            (
                (
                    "remove",
                    lambda _action, address, _data: tasks.create(
                        self._remove_contact(address.get_string())
                    ),
                    "s",
                ),
            )
        )

    async def _remove_contact(self, address: str):
        response = await cast("Awaitable[str]", self.remove_contact_dialog.choose(self))
        if response == "remove":
            await store.address_book.delete(Address(address))

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
