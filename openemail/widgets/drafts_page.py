# drafts_page.py
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

from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, mail
from openemail.mail import MailMessage

from .compose_dialog import MailComposeDialog
from .content_page import MailContentPage


@Gtk.Template(resource_path=f"{PREFIX}/gtk/drafts-page.ui")
class MailDraftsPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailDraftsPage"

    content: MailContentPage = Gtk.Template.Child()

    compose_dialog = GObject.Property(type=MailComposeDialog)

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
        for message in mail.drafts:
            if not message:
                continue

            mail.drafts.delete(message.draft_id)  # type: ignore

    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not (isinstance(message := selection.get_selected_item(), MailMessage)):
            return

        selection.unselect_all()

        self.compose_dialog.attached_files.clear()
        self.compose_dialog.attachments.remove_all()
        self.compose_dialog.broadcast_switch.set_active(message.broadcast)
        self.compose_dialog.subject_id = message.subject_id
        self.compose_dialog.draft_id = message.draft_id
        self.compose_dialog.readers.set_text(message.name)
        self.compose_dialog.subject.set_text(message.subject)
        self.compose_dialog.body.set_text(message.body)

        self.compose_dialog.present(self)
