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

from datetime import datetime
from re import M, sub
from typing import Any, Literal

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX, mail, settings
from openemail.core.model import Envelope
from openemail.mail import MailMessage

from .compose_dialog import MailComposeDialog
from .content_page import MailContentPage
from .message_view import MailMessageView


@Gtk.Template(resource_path=f"{PREFIX}/gtk/messages-page.ui")
class MailMessagesPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailMessagesPage"

    content: MailContentPage = Gtk.Template.Child()
    message_view: MailMessageView = Gtk.Template.Child()

    title = GObject.Property(type=str, default=_("Messages"))
    compose_dialog = GObject.Property(type=MailComposeDialog)

    _folder: str | None = None

    @GObject.Property(type=str)
    def folder(self) -> str | None:
        """Get the folder this page represents."""
        return self._folder

    @folder.setter
    def folder(self, folder: Literal["broadcasts", "inbox", "outbox", "trash"]) -> None:
        match folder:
            case "broadcasts":
                self.title = _("Broadcasts")
                model = mail.broadcasts
            case "inbox":
                self.title = _("Inbox")
                model = mail.inbox
            case "outbox":
                self.title = _("Outbox")
                model = mail.outbox
            case "trash":
                self.title = _("Trash")
                inboxes = Gio.ListStore.new(Gio.ListModel)
                inboxes.append(mail.broadcasts)
                inboxes.append(mail.inbox)
                model = Gtk.FlattenListModel.new(inboxes)

        self.content.model = Gtk.SingleSelection(
            autoselect=False,
            model=Gtk.SortListModel.new(
                Gtk.FilterListModel.new(
                    model,
                    (
                        filter := Gtk.CustomFilter.new(
                            lambda item: (
                                item.trashed
                                if folder == "trash"
                                else (not item.trashed)
                            )
                            and (
                                (
                                    (lowered := self.content.search_text.lower())
                                    in item.name.lower()
                                    or lowered in item.subject.lower()
                                    or lowered in item.body.lower()
                                )
                                if self.content.search_text
                                else True
                            )
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
                    )
                ),
            ),
        )

        def on_trash_changed(_obj: Any, key: str) -> None:
            filter.changed(Gtk.FilterChange.DIFFERENT)
            self.content.model.set_selected(0)

        settings.connect("changed::trashed-messages", on_trash_changed)
        self.content.connect(
            "notify::search-text",
            lambda *_: filter.changed(
                Gtk.FilterChange.DIFFERENT,
            ),
        )

        self.content.model.connect("notify::selected", self.__on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/gtk/message-row.ui"
        )

        self._folder = folder

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.message_view.reply_button.connect("clicked", self.__reply)

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
        self.compose_dialog.subject_id = None
        self.compose_dialog.draft_id = None
        self.compose_dialog.broadcast_switch.set_active(False)
        self.compose_dialog.attached_files.clear()
        self.compose_dialog.attachments.remove_all()
        self.compose_dialog.compose_form.reset()

        self.compose_dialog.present(self)
        self.compose_dialog.readers.grab_focus()

    def __reply(self, *_args: Any) -> None:
        if not self.message_view.message:
            return self._new_message()

        envelope: Envelope = self.message_view.message.envelope

        self.compose_dialog.attached_files.clear()
        self.compose_dialog.attachments.remove_all()
        self.compose_dialog.compose_form.reset()
        self.compose_dialog.broadcast_switch.set_active(
            bool(envelope.is_broadcast and (envelope.author == mail.user.address))
        )
        self.compose_dialog.readers.set_text(
            ", ".join(
                str(reader)
                for reader in list(dict.fromkeys(envelope.readers + [envelope.author]))
                if (reader != mail.user.address)
            )
        )

        if body := self.message_view.message.body:
            self.compose_dialog.body.set_text(
                # Date, time, author
                _("On {}, {}, {} wrote:").format(
                    envelope.date.strftime("%x"),
                    envelope.date.astimezone(datetime.now().tzinfo).strftime("%H:%M"),
                    profile.name
                    if (profile := mail.profiles.get(envelope.author))
                    else envelope.author,
                )
                + "\n"
                + sub(r"^(?!>)", r"> ", body, flags=M)
                + "\n\n"
            )

        self.compose_dialog.subject.set_text(envelope.subject)
        self.compose_dialog.subject_id = envelope.subject_id
        self.compose_dialog.draft_id = None

        self.compose_dialog.present(self)
        self.compose_dialog.body_view.grab_focus()

    def __on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not (
            isinstance(
                selected := selection.get_selected_item(),
                MailMessage,
            )
            and selected.message
        ):
            self.message_view.visible_child_name = "empty"
            self.message_view.author_is_self = False
            self.message_view.can_trash = False
            self.message_view.can_restore = False
            self.message_view.can_reply = False
            return

        self.message_view.set_from_message(selected.message)
        self.content.split_view.set_show_content(True)
