# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from collections.abc import Awaitable, Iterable
from typing import Any, cast

from gi.repository import Adw, Gio, GLib, Gtk

from openemail import PREFIX, mail, run_task
from openemail.mail import Address, Message, Profile

from .form import Form
from .message_body import MessageBody


@Gtk.Template(resource_path=f"{PREFIX}/gtk/compose-dialog.ui")
class ComposeDialog(Adw.Dialog):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "ComposeDialog"

    broadcast_switch: Gtk.Switch = Gtk.Template.Child()
    readers: Gtk.Text = Gtk.Template.Child()
    subject: Gtk.Text = Gtk.Template.Child()
    body_view: MessageBody = Gtk.Template.Child()
    compose_form: Form = Gtk.Template.Child()

    attachments: Gtk.ListBox = Gtk.Template.Child()

    body: Gtk.TextBuffer
    subject_id: str | None = None
    draft_id: int | None = None

    attached_files: dict[Gio.File, str]
    _save: bool = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attached_files = {}
        self.body = self.body_view.props.buffer

    def present_new(self, parent: Gtk.Widget) -> None:
        """Present `self` with empty contents."""
        self.subject_id = None
        self.draft_id = None
        self.broadcast_switch.props.active = False
        self.attached_files.clear()
        self.attachments.remove_all()
        self.compose_form.reset()

        self.present(parent)
        self.readers.grab_focus()

    def present_message(self, message: Message, parent: Gtk.Widget) -> None:
        """Present `self`, displaying the contents of `message`."""
        self.attached_files.clear()
        self.attachments.remove_all()
        self.broadcast_switch.props.active = message.broadcast
        self.subject_id = message.subject_id
        self.draft_id = message.draft_id
        self.readers.props.text = message.name
        self.subject.props.text = message.subject
        self.body.props.text = message.body

        self.present(parent)

    def present_reply(self, message: Message, parent: Gtk.Widget) -> None:
        """Present `self`, replying to `message`."""
        self.attached_files.clear()
        self.attachments.remove_all()
        self.compose_form.reset()
        self.broadcast_switch.props.active = (
            message.broadcast and message.author_is_self
        )
        self.readers.props.text = message.reader_addresses

        if body := message.body:
            self.body.props.text = (
                # Date and time, author
                _("On {}, {} wrote:").format(message.datetime, message.name)
                + "\n"
                + re.sub(r"^(?!>)", r"> ", body, flags=re.MULTILINE)
                + "\n\n"
            )

        self.subject.props.text = message.subject
        self.subject_id = message.subject_id
        self.draft_id = None

        self.present(parent)
        self.body_view.grab_focus()

    @Gtk.Template.Callback()
    def _send_message(self, *_args: Any) -> None:
        readers: list[Address] = []
        warnings: dict[Address, str | None] = {}
        if not self.broadcast_switch.props.active:
            for reader in re.split(",|;| ", self.readers.props.text):
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

        alert.connect(
            "response",
            lambda _obj, response: self._send(readers) if response == "send" else None,
        )

        alert.present(self)

    def _send(self, readers: Iterable[Address]) -> None:
        if self.draft_id:
            mail.drafts.delete(self.draft_id)
            self.draft_id = None

        run_task(
            mail.send_message(
                readers,
                self.subject.props.text,
                self.body.props.text,
                self.subject_id,
                attachments=self.attached_files,
            )
        )

        self.subject_id = None
        self._save = False
        self.force_close()

    @Gtk.Template.Callback()
    def _attach_files(self, *_args: Any) -> None:
        run_task(self._attach_files_task())

    @Gtk.Template.Callback()
    def _reveal_readers(self, revealer: Gtk.Revealer, *_args: Any) -> None:
        self.compose_form.address_lists = Gtk.StringList.new(
            ("readers",) if revealer.props.reveal_child else ()
        )

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
    def _closed(self, *_args: Any) -> None:
        if not self._save:
            self._save = True
            return

        subject = self.subject.props.text
        body = self.body.props.text

        if not (subject or body):
            return

        mail.drafts.save(
            self.readers.props.text,
            subject,
            body,
            self.subject_id,
            self.broadcast_switch.props.active,
            self.draft_id,
        )

    @Gtk.Template.Callback()
    def _insert_emoji(self, *_args: Any) -> None:
        Gtk.TextView.do_insert_emoji(self.body_view)

    async def _attach_files_task(self) -> None:
        try:
            gfiles = await cast(
                "Awaitable[Gio.ListModel]",
                Gtk.FileDialog().open_multiple(
                    win if isinstance(win := self.props.root, Gtk.Window) else None
                ),
            )
        except GLib.Error:
            return

        for gfile in gfiles:
            try:
                display_name = (
                    await cast(
                        "Awaitable[Gio.FileInfo]",
                        (gfile := cast("Gio.File", gfile)).query_info_async(
                            Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME,
                            Gio.FileQueryInfoFlags.NONE,
                            GLib.PRIORITY_DEFAULT,
                        ),
                    )
                ).get_display_name()
            except GLib.Error:
                continue

            self.attached_files[gfile] = display_name
            row = Adw.ActionRow(title=display_name, use_markup=False)
            row.add_prefix(Gtk.Image.new_from_icon_name("mail-attachment-symbolic"))
            self.attachments.append(row)

    def _format_line(self, syntax: str, toggle: bool = False) -> None:
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
