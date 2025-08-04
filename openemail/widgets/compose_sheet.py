# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from collections.abc import Iterable
from typing import Any

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX, create_task
from openemail.app import mail
from openemail.app.mail import (
    ADDRESS_SPLIT_PATTERN,
    Address,
    Message,
    OutgoingAttachment,
    Profile,
)

from .attachments import Attachments
from .body import Body
from .form import Form


@Gtk.Template.from_resource(f"{PREFIX}/compose-sheet.ui")
class ComposeSheet(Adw.BreakpointBin):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "ComposeSheet"

    bottom_sheet: Adw.BottomSheet = Gtk.Template.Child()
    readers: Gtk.Text = Gtk.Template.Child()
    subject: Gtk.Text = Gtk.Template.Child()
    body_view: Body = Gtk.Template.Child()
    compose_form: Form = Gtk.Template.Child()

    attachments: Attachments = Gtk.Template.Child()

    body: Gtk.TextBuffer
    subject_id: str | None = None
    ident: str | None = None

    content = GObject.Property(type=Gtk.Widget)
    privacy = GObject.Property(type=str, default="private")

    _save: bool = True
    _completion_running = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attachments.model = Gio.ListStore.new(OutgoingAttachment)
        self.body = self.body_view.props.buffer
        self.bind_property(
            "content",
            self.bottom_sheet,
            "content",
            GObject.BindingFlags.BIDIRECTIONAL,
        )

    def new_message(self) -> None:
        """Open `self` with empty contents."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._save_draft()

        self.subject_id = None
        self.ident = None
        self.privacy = "private"
        self.attachments.model.remove_all()
        self.compose_form.reset()

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True
        self.readers.grab_focus()

    def open_message(self, message: Message) -> None:
        """Open `self` with `message`."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._save_draft()

        self.attachments.model.remove_all()
        self.privacy = "public" if message.broadcast else "private"
        self.subject_id = message.subject_id
        self.ident = message.draft_id
        self.readers.props.text = message.reader_addresses
        self.subject.props.text = message.subject
        self.body.props.text = message.body

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True

    def reply(self, message: Message) -> None:
        """Open `self`, replying to `message`."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._save_draft()

        self.attachments.model.remove_all()
        self.compose_form.reset()
        self.privacy = (
            "public" if (message.broadcast and message.outgoing) else "private"
        )
        self.readers.props.text = message.reader_addresses

        # Discuss whether this is needed

        # if body := message.body:
        #     self.body.props.text = (
        #         # Date and time, author
        #         _("On {}, {} wrote:").format(message.datetime, message.name)
        #         + "\n"
        #         + re.sub(r"^(?!>)", r"> ", body, flags=re.MULTILINE)
        #         + "\n\n"
        #     )

        self.subject.props.text = message.subject
        self.subject_id = message.subject_id
        self.ident = None

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True
        self.body_view.grab_focus()

    @Gtk.Template.Callback()
    def _readers_insert_text(self, readers: Gtk.Text, *_args: Any) -> None:
        if self._completion_running:
            return

        def complete(*_args: Any) -> None:
            readers.disconnect_by_func(complete)

            pos = readers.props.cursor_position
            start = re.split(ADDRESS_SPLIT_PATTERN, readers.props.text[:pos])[-1]

            if not start:
                return

            for contact in mail.address_book:
                if not (contact.address and contact.address.startswith(start)):
                    continue

                end = contact.address[len(start) :]

                self._completion_running = True
                readers.insert_text(end, pos)  # pyright: ignore[reportUnknownMemberType]
                self._completion_running = False

                readers.select_region(pos, pos + len(end))
                break

        readers.connect("changed", complete)

    @Gtk.Template.Callback()
    def _send_message(self, *_args: Any) -> None:
        readers = list[Address]()
        warnings = dict[Address, str | None]()
        if self.privacy == "private":
            for reader in re.split(ADDRESS_SPLIT_PATTERN, self.readers.props.text):
                if not reader:
                    continue

                try:
                    readers.append(address := Address(reader))
                except ValueError:
                    return

                if Profile.of(address).value_of("away"):
                    warnings[address] = Profile.of(address).value_of("away-warning")

        if not warnings:
            self._send(readers)
            return

        alert = Adw.AlertDialog.new(
            _("Send Message?"),
            _("The following readers indicated that they are away and may not see it:")
            + "\n",
        )

        for address, warning in warnings.items():
            alert.props.body += f"\n{Profile.of(address).name}"
            if not warning:
                continue

            alert.props.body += f": “{warning}”"

        alert.add_response("close", _("Cancel"))
        alert.add_response("send", _("Send"))
        alert.set_response_appearance("send", Adw.ResponseAppearance.SUGGESTED)
        alert.set_default_response("send")

        alert.connect("response::send", lambda *_: self._send(readers))

        alert.present(self)

    def _send(self, readers: Iterable[Address]) -> None:
        if self.ident:
            mail.drafts.delete(self.ident)
            self.ident = None

        create_task(
            mail.send_message(
                readers,
                self.subject.props.text,
                self.body.props.text,
                self.subject_id,
                attachments=tuple(
                    a
                    for a in self.attachments.model
                    if isinstance(a, OutgoingAttachment)
                ),
            )
        )

        self.subject_id = None
        self._save = False
        self._cancel()

    @Gtk.Template.Callback()
    def _attach_files(self, *_args: Any) -> None:
        create_task(self._attach_files_task())

    @Gtk.Template.Callback()
    def _format_bold(self, *_args: Any) -> None:
        self._format_inline("**")

    @Gtk.Template.Callback()
    def _format_italic(self, *_args: Any) -> None:
        self._format_inline("*")

    @Gtk.Template.Callback()
    def _format_strikethrough(self, *_args: Any) -> None:
        self._format_inline("~~")

    @Gtk.Template.Callback()
    def _format_heading(self, *_args: Any) -> None:
        self._format_line("#")

    @Gtk.Template.Callback()
    def _format_quote(self, *_args: Any) -> None:
        self._format_line(">", toggle=True)

    @Gtk.Template.Callback()
    def _insert_emoji(self, *_args: Any) -> None:
        Gtk.TextView.do_insert_emoji(self.body_view)

    async def _attach_files_task(self) -> None:
        async for attachment in OutgoingAttachment.choose(self):
            self.attachments.model.append(attachment)

    def _format_line(self, syntax: str, *, toggle: bool = False) -> None:
        start = self.body.get_iter_at_offset(self.body.props.cursor_position)
        start.set_line_offset(0)

        lookup = f"{syntax} " if toggle else syntax
        syntax_start = self.body.get_iter_at_offset(start.get_offset() + len(lookup))

        if lookup == self.body.get_text(start, syntax_start, include_hidden_chars=True):
            if toggle:
                self.body.delete(start, syntax_start)
            else:
                self.body.insert(start, syntax)
        else:
            self.body.insert(start, f"{syntax} ")

        self.body_view.grab_focus()

    def _format_inline(self, syntax: str) -> None:
        self.body.begin_user_action()
        empty = False

        if bounds := self.body.get_selection_bounds():
            start, end = bounds
        else:
            start = self.body.get_iter_at_offset(self.body.props.cursor_position)
            end = start.copy()

            if start.inside_word() or start.starts_word() or end.ends_word():
                if not start.starts_word():
                    start.backward_word_start()

                if not end.ends_word():
                    end.forward_word_end()
            else:
                empty = True

        text = self.body.get_text(start, end, include_hidden_chars=True)

        syntax_start = self.body.get_iter_at_offset(start.get_offset() - len(syntax))
        syntax_end = self.body.get_iter_at_offset(end.get_offset() + len(syntax))

        if (
            syntax
            == self.body.get_text(start, syntax_start, include_hidden_chars=True)
            == self.body.get_text(end, syntax_end, include_hidden_chars=True)
        ):
            self.body.delete(syntax_start, syntax_end)
            self.body.insert(syntax_start, text)
        else:
            self.body.delete(start, end)
            self.body.insert(start, f"{syntax}{text}{syntax}")

            if empty:
                self.body.place_cursor(
                    self.body.get_iter_at_offset(start.get_offset() - len(syntax))
                )

        self.body.end_user_action()
        self.body_view.grab_focus()

    @Gtk.Template.Callback()
    def _get_readers_field_active(self, _obj: Any, privacy: str) -> bool:
        return privacy == "private"

    @Gtk.Template.Callback()
    def _get_bottom_bar_label(self, _obj: Any, subject: str) -> str:
        return subject or _("New Message")

    def _save_draft(self) -> None:
        if not self._save:
            self._save = True
            return

        subject = self.subject.props.text
        body = self.body.props.text

        if not (subject or body):
            return

        mail.drafts.save(
            self.ident,
            self.readers.props.text,
            subject,
            body,
            self.subject_id,
        )

    @Gtk.Template.Callback()
    def _cancel(self, *_args: Any) -> None:
        self.bottom_sheet.props.reveal_bottom_bar = False
        self.bottom_sheet.props.open = False
        self._save_draft()
