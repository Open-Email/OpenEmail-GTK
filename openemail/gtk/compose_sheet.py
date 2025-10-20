# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from collections.abc import Iterable
from typing import Any

from gi.repository import Adw, Gio, GLib, Gtk

from openemail import PREFIX, Property, message, store, tasks
from openemail.core.model import Address
from openemail.message import Message, OutgoingAttachment
from openemail.profile import Profile
from openemail.store import ADDRESS_SPLIT_PATTERN

from .attachments import Attachments
from .body import Body
from .form import Form

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/compose-sheet.ui")
class ComposeSheet(Adw.BreakpointBin):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = __qualname__

    bottom_sheet: Adw.BottomSheet = child
    readers: Gtk.Text = child
    subject: Gtk.Text = child
    body_view: Body = child
    compose_form: Form = child

    attachments: Attachments = child

    confirm_send_dialog: Adw.AlertDialog = child

    body = Property(Gtk.TextBuffer)
    content = Property(Gtk.Widget)
    privacy = Property(str, default="private")

    subject_id: str | None = None
    ident: str | None = None

    _completion_running = False
    _readers: Iterable[Address]

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("compose", group := Gio.SimpleActionGroup())
        group.add_action_entries(
            (
                ("format", self._format, "(ss)"),
                ("new", lambda *_: self.new_message()),
                ("draft", self._draft, "s"),
                ("reply", self._reply, "s"),
            )
        )

    def new_message(self):
        """Open `self` with empty contents."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._cancel()

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True
        self.readers.grab_focus()

    def open_draft(self, draft: Message):
        """Open `self` with `draft`."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._cancel()

        self.privacy = "public" if draft.is_broadcast else "private"
        self.subject_id = draft.subject_id
        self.ident = draft.unique_id.split()[1]
        self.readers.props.text = draft.readers
        self.subject.props.text = draft.subject
        self.body.props.text = draft.body

        self.bottom_sheet.props.open = True
        self.bottom_sheet.props.reveal_bottom_bar = True

    def reply(self, message: Message):
        """Open `self`, replying to `message`."""
        if self.bottom_sheet.props.reveal_bottom_bar:
            self._cancel()

        own_broadcast = message.is_broadcast and message.is_outgoing
        self.privacy = "public" if own_broadcast else "private"
        self.readers.props.text = message.readers
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

            for contact in store.address_book:
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
            self._readers = ()
            self._confirm_send()
            return

        split = re.split(ADDRESS_SPLIT_PATTERN, self.readers.props.text)
        self._readers = tuple(Address(reader) for reader in split)
        warnings = {
            reader: Profile.of(reader).value_of("away-warning")
            for reader in self._readers
            if Profile.of(reader).value_of("away")
        }

        if not warnings:
            self._confirm_send()
            return

        self.confirm_send_dialog.props.body = (
            _("The following readers indicated that they are away and may not see it:")
            + "\n"
            + "".join(
                f"\n{Profile.of(address).name}{f': “{warning}”' if warning else ''}"
                for address, warning in warnings.items()
            )
        )

        self.confirm_send_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_send(self, *_args):
        if self.ident:
            store.drafts.delete(self.ident)

        tasks.create(
            message.send(
                self._readers,
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
    def _insert_emoji(self, *_args):
        Gtk.TextView.do_insert_emoji(self.body_view)

    @tasks.callback
    async def _attach_files(self, *_args):
        async for attachment in OutgoingAttachment.choose(self):
            self.attachments.model.append(attachment)

    def format_line(self, string: str, /, always_prepend: bool = False):
        """Prepend the current line with `string`.

        Unless `always_prepend` is `True`,
        `string` is removed instead if it is already there.
        """
        start = self.body.get_iter_at_offset(self.body.props.cursor_position)
        start.set_line_offset(0)

        lookup = string if always_prepend else f"{string} "
        string_start = self.body.get_iter_at_offset(start.get_offset() + len(lookup))

        if lookup == self.body.get_text(start, string_start, include_hidden_chars=True):
            if always_prepend:
                self.body.insert(start, string)
            else:
                self.body.delete(start, string_start)
        else:
            self.body.insert(start, f"{string} ")

        self.body_view.grab_focus()

    def format_inline(self, string: str):
        """Wrap the selected text (or cursor if nothing is selected) with `string`.

        If the selection is already wrapped with `string`, it is removed instead.
        """
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

        string_start = self.body.get_iter_at_offset(start.get_offset() - len(string))
        string_end = self.body.get_iter_at_offset(end.get_offset() + len(string))

        if (
            string
            == self.body.get_text(start, string_start, include_hidden_chars=True)
            == self.body.get_text(end, string_end, include_hidden_chars=True)
        ):
            self.body.delete(string_start, string_end)
            self.body.insert(string_start, text)
        else:
            self.body.delete(start, end)
            self.body.insert(start, f"{string}{text}{string}")

            if empty:
                self.body.place_cursor(
                    self.body.get_iter_at_offset(start.get_offset() - len(string))
                )

        self.body.end_user_action()
        self.body_view.grab_focus()

    def _format(self, _name, param: GLib.Variant, *_args):
        kind, string = param.unpack()
        match kind:
            case "inline":
                self.format_inline(string)
            case "line":
                self.format_line(string)
            case "always-prepend":
                self.format_line(string, always_prepend=True)

    def _draft(self, _name, param: GLib.Variant, *_args):
        if draft := store.drafts.get(param.get_string()):
            self.open_draft(draft)

    def _reply(self, _name, param: GLib.Variant, *_args):
        ident = param.get_string()
        for msgs in store.inbox, store.outbox, store.sent, store.broadcasts:
            if msg := msgs.get(ident):
                self.reply(msg)
                return

    def _close(self):
        self.bottom_sheet.props.reveal_bottom_bar = False
        self.bottom_sheet.props.open = False

        self.subject_id = None
        self.ident = None
        self.privacy = "private"

        if hasattr(self, "_redaers"):
            del self._readers

        self.compose_form.reset()
        self.attachments.model.remove_all()

    @Gtk.Template.Callback()
    def _cancel(self, *_args):
        subject = self.subject.props.text
        body = self.body.props.text
        if subject or body:
            readers = self.readers.props.text
            store.drafts.save(
                self.ident,
                readers,
                subject,
                body,
                self.subject_id,
                self.privacy == "public",
            )

        self._close()

    @Gtk.Template.Callback()
    def _get_readers_field_active(self, _obj, privacy: str) -> bool:
        return privacy == "private"

    @Gtk.Template.Callback()
    def _get_bottom_bar_label(self, _obj, subject: str) -> str:
        return subject or _("New Message")
