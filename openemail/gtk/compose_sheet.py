# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from collections.abc import Iterable
from typing import Any, Self

from gi.repository import Adw, Gio, Gtk

import openemail as app
from openemail import (
    ADDRESS_SPLIT_PATTERN,
    PREFIX,
    Address,
    Message,
    OutgoingAttachment,
    Profile,
    Property,
)

from .attachments import Attachments
from .body import Body
from .form import Form

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/compose-sheet.ui")
class ComposeSheet(Adw.BreakpointBin):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "ComposeSheet"

    default: Self

    bottom_sheet: Adw.BottomSheet = child
    readers: Gtk.Text = child
    subject: Gtk.Text = child
    body_view: Body = child
    compose_form: Form = child

    attachments: Attachments = child

    body: Gtk.TextBuffer
    subject_id: str | None = None
    ident: str | None = None

    content = Property(Gtk.Widget)
    privacy = Property(str, default="private")

    _completion_running = False

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.attachments.model = Gio.ListStore.new(OutgoingAttachment)
        self.body = self.body_view.props.buffer
        Property.bind(self, "content", self.bottom_sheet, bidirectional=True)

    def new_message(self):
        """Open `self` with empty contents."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._cancel()

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True
        self.readers.grab_focus()

    def open_message(self, message: Message):
        """Open `self` with `message`."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._cancel()

        self.privacy = "public" if message.broadcast else "private"
        self.subject_id = message.subject_id
        self.ident = message.draft_id
        self.readers.props.text = message.reader_addresses
        self.subject.props.text = message.subject
        self.body.props.text = message.body

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True

    def reply(self, message: Message):
        """Open `self`, replying to `message`."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._cancel()

        own_broadcast = message.broadcast and message.outgoing
        self.privacy = "public" if own_broadcast else "private"
        self.readers.props.text = message.reader_addresses
        self.subject.props.text = message.subject
        self.subject_id = message.subject_id

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True
        self.body_view.grab_focus()

    @Gtk.Template.Callback()
    def _readers_insert_text(self, readers: Gtk.Text, *_args):
        if self._completion_running:
            return

        def complete(*_args):
            readers.disconnect_by_func(complete)

            pos = readers.props.cursor_position
            start = re.split(ADDRESS_SPLIT_PATTERN, readers.props.text[:pos])[-1]

            if not start:
                return

            for contact in app.address_book:
                if not (contact.address and contact.address.startswith(start)):
                    continue

                end = contact.address[len(start) :]

                self._completion_running = True
                readers.insert_text(end, pos)
                self._completion_running = False

                readers.select_region(pos, pos + len(end))
                break

        readers.connect("changed", complete)

    @Gtk.Template.Callback()
    def _send_message(self, *_args):
        if self.privacy == "public":
            self._confirm_send(())
            return

        split = re.split(ADDRESS_SPLIT_PATTERN, self.readers.props.text)
        readers = tuple(Address(reader) for reader in split)
        warnings = {
            reader: Profile.of(reader).value_of("away-warning")
            for reader in readers
            if Profile.of(reader).value_of("away")
        }

        if not warnings:
            self._confirm_send(readers)
            return

        alert = Adw.AlertDialog.new(
            _("Send Message?"),
            _("The following readers indicated that they are away and may not see it:")
            + "\n"
            + "".join(
                f"\n{Profile.of(address).name}{f': “{warning}”' if warning else ''}"
                for address, warning in warnings.items()
            ),
        )

        alert.add_response("close", _("Cancel"))
        alert.add_response("send", _("Send"))
        alert.set_response_appearance("send", Adw.ResponseAppearance.SUGGESTED)
        alert.set_default_response("send")
        alert.connect("response::send", lambda *_: self._confirm_send(readers))

        alert.present(self)

    def _confirm_send(self, readers: Iterable[Address]):
        if self.ident:
            app.drafts.delete(self.ident)

        app.create_task(
            app.send_message(
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

        self._close()

    @Gtk.Template.Callback()
    def _attach_files(self, *_args):
        app.create_task(self._attach_files_task())

    @Gtk.Template.Callback()
    def _format_bold(self, *_args):
        self._format_inline("**")

    @Gtk.Template.Callback()
    def _format_italic(self, *_args):
        self._format_inline("*")

    @Gtk.Template.Callback()
    def _format_strikethrough(self, *_args):
        self._format_inline("~~")

    @Gtk.Template.Callback()
    def _format_heading(self, *_args):
        self._format_line("#")

    @Gtk.Template.Callback()
    def _format_quote(self, *_args):
        self._format_line(">", toggle=True)

    @Gtk.Template.Callback()
    def _insert_emoji(self, *_args):
        Gtk.TextView.do_insert_emoji(self.body_view)

    async def _attach_files_task(self):
        async for attachment in OutgoingAttachment.choose(self):
            self.attachments.model.append(attachment)

    def _format_line(self, syntax: str, *, toggle: bool = False):
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

    def _format_inline(self, syntax: str):
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

    def _close(self):
        self.bottom_sheet.props.reveal_bottom_bar = False
        self.bottom_sheet.props.open = False

        self.subject_id = None
        self.ident = None
        self.privacy = "private"

        self.compose_form.reset()
        self.attachments.model.remove_all()

    @Gtk.Template.Callback()
    def _cancel(self, *_args):
        subject = self.subject.props.text
        body = self.body.props.text
        if subject or body:
            readers = self.readers.props.text
            app.drafts.save(self.ident, readers, subject, body, self.subject_id)

        self._close()

    @Gtk.Template.Callback()
    def _get_readers_field_active(self, _obj, privacy: str) -> bool:
        return privacy == "private"

    @Gtk.Template.Callback()
    def _get_bottom_bar_label(self, _obj, subject: str) -> str:
        return subject or _("New Message")
