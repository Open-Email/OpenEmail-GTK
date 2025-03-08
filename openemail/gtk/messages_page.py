# messages_page.py
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

from typing import Any, Literal

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import shared
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.message_view import MailMessageView


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/messages-page.ui")
class MailMessagesPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailMessagesPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    message_view: MailMessageView = Gtk.Template.Child()  # type: ignore

    title = GObject.Property(type=str, default=_("Messages"))
    _folder: str | None = None

    @GObject.Property(type=str)
    def folder(self) -> str | None:
        """Get the folder this page represents."""
        return self._folder

    @folder.setter
    def folder(self, folder: Literal["inbox", "broadcasts", "outbox"]) -> None:
        model: Gio.ListModel
        match folder:
            case "inbox":
                self.title = _("Inbox")
                model = shared.inbox
            case "broadcasts":
                self.title = _("Broadcasts")
                model = shared.broadcasts
            case "outbox":
                self.title = _("Outbox")
                model = shared.outbox

        self.content.model = (
            selection := Gtk.SingleSelection(
                autoselect=False,
                model=Gtk.SortListModel.new(
                    model,
                    Gtk.CustomSorter.new(
                        lambda a, b, _: int(
                            b.message.envelope.date.timestamp()
                            > a.message.envelope.date.timestamp()
                        )
                        - int(
                            b.message.envelope.date.timestamp()
                            < a.message.envelope.date.timestamp()
                        )  # type: ignore
                    ),
                ),
            )
        )

        selection.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{shared.PREFIX}/gtk/message-row.ui"
        )

        self._folder = folder

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:  # type: ignore
        if not isinstance(
            selected := selection.get_selected_item(),
            shared.MailMessage,
        ):
            return

        self.message_view.set_from_message(selected.message)
        self.content.split_view.set_show_content(True)
