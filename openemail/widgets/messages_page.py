# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from re import M, sub
from typing import Any, Literal

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX, mail, settings
from openemail.mail import MailMessage, empty_trash

from .compose_dialog import MailComposeDialog
from .content_page import MailContentPage
from .message_view import MailMessageView


@Gtk.Template(resource_path=f"{PREFIX}/gtk/messages-page.ui")
class MailMessagesPage(Adw.NavigationPage):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailMessagesPage"

    content: MailContentPage = Gtk.Template.Child()
    message_view: MailMessageView = Gtk.Template.Child()

    confirm_empty_dialog = Gtk.Template.Child()

    title = GObject.Property(type=str, default=_("Messages"))
    compose_dialog = GObject.Property(type=MailComposeDialog)

    _folder: str | None = None

    @GObject.Property(
        type=str,
        flags=GObject.PARAM_STATIC_STRINGS
        | GObject.PARAM_READABLE
        | GObject.PARAM_WRITABLE
        | GObject.PARAM_CONSTRUCT_ONLY,
    )
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

                (
                    empty_button := Gtk.Button(
                        icon_name="trash-symbolic",
                        tooltip_text=_("Empty Trash"),
                    )
                ).connect("clicked", lambda *_: self.confirm_empty_dialog.present(self))
                self.content.toolbar_button = empty_button

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
                        b.message.date.timestamp() > a.message.date.timestamp()
                    )
                    - int(b.message.date.timestamp() < a.message.date.timestamp())
                ),
            ),
        )

        def on_trash_changed(_obj: Any, key: str) -> None:
            filter.changed(Gtk.FilterChange.DIFFERENT)
            self.content.model.props.selected = 0

        settings.connect("changed::trashed-messages", on_trash_changed)
        self.content.connect(
            "notify::search-text",
            lambda *_: filter.changed(
                Gtk.FilterChange.DIFFERENT,
            ),
        )

        self.content.model.bind_property("selected-item", self.message_view, "message")
        self.content.model.connect("notify::selected", self._on_selected)

        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/gtk/message-row.ui"
        )

        self._folder = folder

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.message_view.reply_button.connect("clicked", self._reply)

    @Gtk.Template.Callback()
    def _confirm_empty(self, _obj: Any, response: str) -> None:
        if response != "empty":
            return

        empty_trash()

    @Gtk.Template.Callback()
    def _new_message(self, *_args: Any) -> None:
        self.compose_dialog.subject_id = None
        self.compose_dialog.draft_id = None
        self.compose_dialog.broadcast_switch.props.active = False
        self.compose_dialog.attached_files.clear()
        self.compose_dialog.attachments.remove_all()
        self.compose_dialog.compose_form.reset()

        self.compose_dialog.present(self)
        self.compose_dialog.readers.grab_focus()

    def _reply(self, *_args: Any) -> None:
        if not self.message_view.message:
            return self._new_message()

        message: MailMessage = self.message_view.message

        self.compose_dialog.attached_files.clear()
        self.compose_dialog.attachments.remove_all()
        self.compose_dialog.compose_form.reset()
        self.compose_dialog.broadcast_switch.props.active = (
            message.broadcast and message.author_is_self
        )
        self.compose_dialog.readers.props.text = message.reader_addresses

        if body := self.message_view.message.body:
            self.compose_dialog.body.props.text = (
                # Date and time, author
                _("On {}, {} wrote:").format(message.datetime, message.name)
                + "\n"
                + sub(r"^(?!>)", r"> ", body, flags=M)
                + "\n\n"
            )

        self.compose_dialog.subject.props.text = message.subject
        self.compose_dialog.subject_id = message.subject_id
        self.compose_dialog.draft_id = None

        self.compose_dialog.present(self)
        self.compose_dialog.body_view.grab_focus()

    def _on_selected(self, selection: Gtk.SingleSelection, *_args: Any) -> None:
        if not isinstance(selected := selection.props.selected_item, MailMessage):
            return

        selected.mark_read()
        self.content.split_view.props.show_content = True
