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
from openemail.network import send_message
from openemail.user import Address


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/messages-page.ui")
class MailMessagesPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailMessagesPage"

    content: MailContentPage = Gtk.Template.Child()  # type: ignore
    message_view: MailMessageView = Gtk.Template.Child()  # type: ignore

    compose_dialog: Adw.Dialog = Gtk.Template.Child()
    broadcast_switch: Gtk.Switch = Gtk.Template.Child()
    subject: Gtk.Text = Gtk.Template.Child()
    readers: Gtk.Text = Gtk.Template.Child()
    body: Gtk.TextView = Gtk.Template.Child()

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
            case "broadcasts":
                self.title = _("Broadcasts")
                model = shared.broadcasts
            case "inbox":
                self.title = _("Inbox")
                model = shared.inbox
            case "outbox":
                self.title = _("Outbox")
                model = shared.outbox
            case "trash":
                self.title = _("Trash")
                inboxes = Gio.ListStore.new(Gio.ListModel)
                inboxes.append(shared.broadcasts)
                inboxes.append(shared.inbox)
                model = Gtk.FlattenListModel.new(inboxes)

        self.content.model = selection = Gtk.SingleSelection(
            autoselect=False,
            model=Gtk.SortListModel.new(
                Gtk.FilterListModel.new(
                    model,
                    (
                        filter := Gtk.CustomFilter.new(
                            lambda item: item.trashed
                            if folder == "trash"
                            else (not item.trashed)
                        )
                    ),
                ),
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

        def on_settings_changed(_obj: Any, key: str) -> None:
            if key != "trashed-message-ids":
                return

            filter.changed(Gtk.FilterChange.DIFFERENT)
            selection.set_selected(0)

        shared.settings.connect("changed", on_settings_changed)

        selection.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{shared.PREFIX}/gtk/message-row.ui"
        )

        self._folder = folder

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.add_controller(
            controller := Gtk.ShortcutController(
                scope=Gtk.ShortcutScope.GLOBAL,
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>n"),
                Gtk.CallbackAction.new(lambda *_: not (self._new_message())),
            )
        )

    @Gtk.Template.Callback()
    def _new_message(self, *_args: Any) -> None:
        self.readers.set_text("")
        self.subject.set_text("")
        self.body.get_buffer().set_text("")
        self.broadcast_switch.set_active(False)

        self.compose_dialog.present(self)
        self.readers.grab_focus()

    @Gtk.Template.Callback()
    def _send_message(self, *_args: Any) -> None:
        if not shared.user:
            return

        readers: list[Address] = []
        if not self.broadcast_switch.get_active():
            for reader in self.readers.get_text().split(","):
                try:
                    readers.append(Address(reader.strip()))
                except ValueError:
                    return

        shared.run_task(
            send_message(
                shared.user,
                readers,
                self.subject.get_text(),
                (buffer := self.body.get_buffer()).get_text(
                    buffer.get_start_iter(),
                    buffer.get_end_iter(),
                    False,
                ),
            ),
            lambda: shared.run_task(shared.update_outbox()),
        )

        self.compose_dialog.force_close()

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:  # type: ignore
        if not isinstance(
            selected := selection.get_selected_item(),
            shared.MailMessage,
        ):
            self.message_view.visible_child_name = "empty"
            self.message_view.author_is_self = False
            self.message_view.can_trash = False
            self.message_view.can_restore = False
            return

        self.message_view.set_from_message(selected.message)
        self.content.split_view.set_show_content(True)
