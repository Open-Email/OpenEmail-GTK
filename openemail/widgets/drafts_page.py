# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, mail
from openemail.mail import Message

from .compose_dialog import ComposeDialog
from .content_page import ContentPage


@Gtk.Template(resource_path=f"{PREFIX}/gtk/drafts-page.ui")
class DraftsPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "DraftsPage"

    content: ContentPage = Gtk.Template.Child()

    compose_dialog = GObject.Property(type=ComposeDialog)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.content.model = Gtk.SingleSelection(
            autoselect=False,
            model=Gtk.FilterListModel.new(
                mail.drafts,
                filter := Gtk.CustomFilter.new(
                    lambda item: (
                        (lowered := self.content.search_text.lower())
                        in item.name.lower()
                        or lowered in item.subject.lower()
                        or lowered in item.body.lower()
                    )
                    if self.content.search_text
                    else True
                ),
            ),
        )

        self.content.connect(
            "notify::search-text",
            lambda *_: filter.changed(
                Gtk.FilterChange.DIFFERENT,
            ),
        )

        self.content.model.connect("notify::selected", self._on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/gtk/message-row.ui"
        )

    @Gtk.Template.Callback()
    def _delete_all(self, *_args: Any) -> None:
        mail.drafts.delete_all()

    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not (isinstance(message := selection.props.selected_item, Message)):
            return

        selection.unselect_all()

        self.compose_dialog.attached_files.clear()
        self.compose_dialog.attachments.remove_all()
        self.compose_dialog.broadcast_switch.props.active = message.broadcast
        self.compose_dialog.subject_id = message.subject_id
        self.compose_dialog.draft_id = message.draft_id
        self.compose_dialog.readers.props.text = message.name
        self.compose_dialog.subject.props.text = message.subject
        self.compose_dialog.body.props.text = message.body

        self.compose_dialog.present(self)
