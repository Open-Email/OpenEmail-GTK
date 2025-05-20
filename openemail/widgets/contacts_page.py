# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from locale import strcoll
from typing import Any

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX, mail, run_task
from openemail.mail import Address

from .content_page import ContentPage
from .form import Form
from .profile_view import ProfileView
from .request_buttons import RequestButtons  # noqa: F401


@Gtk.Template(resource_path=f"{PREFIX}/gtk/contacts-page.ui")
class ContactsPage(Adw.NavigationPage):
    """A page with the contents of the user's address book."""

    __gtype_name__ = "ContactsPage"

    content: ContentPage = Gtk.Template.Child()
    profile_view: ProfileView = Gtk.Template.Child()

    add_contact_dialog: Adw.AlertDialog = Gtk.Template.Child()
    address: Adw.EntryRow = Gtk.Template.Child()
    address_form: Form = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        models = Gio.ListStore.new(Gio.ListModel)
        models.append(mail.contact_requests)
        models.append(mail.address_book)

        self.content.model = Gtk.SingleSelection(
            autoselect=False,
            model=Gtk.SortListModel.new(
                Gtk.FilterListModel.new(
                    Gtk.FlattenListModel.new(models),
                    (
                        search_filter := Gtk.CustomFilter.new(
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
                Gtk.CustomSorter.new(
                    lambda a, b, _: (b.contact_request - a.contact_request)
                    or strcoll(a.name, b.name)
                ),
            ),
        )

        mail.address_book.bind_property(
            "updating",
            self.content,
            "loading",
            GObject.BindingFlags.SYNC_CREATE,
        )

        self.content.connect(
            "notify::search-text",
            lambda *_: search_filter.changed(Gtk.FilterChange.DIFFERENT),
        )

        self.content.model.bind_property("selected-item", self.profile_view, "profile")
        self.content.model.connect("notify::selected", self._on_selected)

        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/gtk/contact-row.ui"
        )

    @Gtk.Template.Callback()
    def _new_contact(self, *_args: Any) -> None:
        self.address_form.reset()
        self.add_contact_dialog.present(self)

    @Gtk.Template.Callback()
    def _add_contact(self, *_args: Any) -> None:
        try:
            run_task(mail.address_book.new(Address(self.address.props.text)))
        except ValueError:
            return

    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        self.content.split_view.props.show_content = bool(selection.props.selected_item)
