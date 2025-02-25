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

from email.message import Message
from re import sub
from typing import Any, Sequence

from gi.repository import Adw, Gdk, Gio, GObject, Gtk

from openemail import shared
from openemail.gtk.content_page import MailContentPage
from openemail.gtk.message_view import MailMessageView
from openemail.message import Envelope, Message
from openemail.user import Address


class MailMessage(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "MailMessage"

    message: Message | None = None

    name = GObject.Property(type=str)
    date = GObject.Property(type=str)
    subject = GObject.Property(type=str)
    contents = GObject.Property(type=str)
    stripped_contents = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    def __init__(self, message: Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if message:
            self.set_from_message(message)

    def set_from_message(self, message: Message) -> None:
        """Update properties of the row from `message`."""
        self.message = message

        self.name = shared.get_name(message.envelope.author)
        self.date = message.envelope.date.strftime("%x")
        self.subject = message.envelope.subject
        self.contents = message.contents
        self.stripped_contents = sub(r"\n+", " ", message.contents)
        self.profile_image = shared.get_profile_image(message.envelope.author)


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/messages-page.ui")
class MailMessagesPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailMessagesPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    message_view: MailMessageView = Gtk.Template.Child()  # type: ignore

    messages: Gio.ListStore

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.messages = Gio.ListStore.new(MailMessage)

        self.content.model = (
            selection := Gtk.SingleSelection(
                autoselect=False,
                model=Gtk.SortListModel.new(
                    self.messages,
                    Gtk.CustomSorter.new(
                        lambda a, b, _: int(
                            b.message.envelope.date > a.message.envelope.date
                        )
                        - int(b.message.envelope.date < a.message.envelope.date)  # type: ignore
                    ),
                ),
            )
        )
        selection.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{shared.PREFIX}/gtk/message-row.ui"
        )

    def set_loading(self, loading: bool) -> None:
        """Set whether or not to display a spinner."""
        self.content.set_loading(loading)

    def update_messages_list(self, messages: Sequence[Message] = ()) -> None:
        """Update the list of messages in the view."""
        self.messages.remove_all()
        for message in messages:
            self.messages.append(MailMessage(message))

        self.set_loading(False)

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:  # type: ignore
        if not isinstance(selected := selection.get_selected_item(), MailMessage):
            return

        self.message_view.set_from_message(selected.message)
