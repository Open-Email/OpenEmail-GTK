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

from typing import Any

from gi.repository import Adw, Gio, GLib, Gtk

from openemail import PREFIX, mail, run_task
from openemail.core.model import Address

from .form import MailForm
from .message_body import MailMessageBody


@Gtk.Template(resource_path=f"{PREFIX}/gtk/compose-dialog.ui")
class MailComposeDialog(Adw.Dialog):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailComposeDialog"

    broadcast_switch: Gtk.Switch = Gtk.Template.Child()
    readers: Gtk.Text = Gtk.Template.Child()
    subject: Gtk.Text = Gtk.Template.Child()
    body_view: MailMessageBody = Gtk.Template.Child()
    compose_form: MailForm = Gtk.Template.Child()

    attachments: Gtk.ListBox = Gtk.Template.Child()

    body: Gtk.TextBuffer
    subject_id: str | None = None
    draft_id: int | None = None

    attached_files: dict[Gio.File, str]
    _save: bool = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attached_files = {}
        self.body = self.body_view.get_buffer()

    @Gtk.Template.Callback()
    def _send_message(self, *_args: Any) -> None:
        readers: list[Address] = []
        if not self.broadcast_switch.get_active():
            for reader in self.readers.get_text().split(","):
                if not (reader := reader.strip()):
                    continue

                try:
                    readers.append(Address(reader))
                except ValueError:
                    return

        if self.draft_id:
            mail.drafts.delete(self.draft_id)
            self.draft_id = None

        run_task(
            mail.send_message(
                readers,
                self.subject.get_text(),
                self.body.get_text(
                    self.body.get_start_iter(),
                    self.body.get_end_iter(),
                    False,
                ),
                self.subject_id,
                attachments=self.attached_files,
            )
        )

        self.subject_id = None
        self._save = False
        self.force_close()

    @Gtk.Template.Callback()
    def _attach_files(self, *_args: Any) -> None:
        run_task(self._attach_files())

    @Gtk.Template.Callback()
    def _reveal_readers(self, revealer: Gtk.Revealer, *_args: Any) -> None:
        self.compose_form.address_lists = Gtk.StringList.new(
            ("readers",) if revealer.get_reveal_child() else ()
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

        subject = self.subject.get_text()
        body = self.body.get_text(
            self.body.get_start_iter(),
            self.body.get_end_iter(),
            False,
        )

        if not (subject or body):
            return

        mail.drafts.save(
            self.readers.get_text(),
            subject,
            body,
            self.subject_id,
            self.broadcast_switch.get_active(),
            self.draft_id,
        )

    async def _attach_files(self) -> None:
        try:
            gfiles = await Gtk.FileDialog().open_multiple(  # type: ignore
                win if isinstance(win := self.get_root(), Gtk.Window) else None
            )
        except GLib.Error:
            return

        for gfile in gfiles:
            try:
                display_name = (
                    await gfile.query_info_async(
                        Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME,
                        Gio.FileQueryInfoFlags.NONE,
                        GLib.PRIORITY_DEFAULT,
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

        if (
            self.body.get_text(
                start,
                (
                    syntax_start := self.body.get_iter_at_offset(
                        start.get_offset()
                        + len((lookup := f"{syntax} " if toggle else syntax))
                    )
                ),
                include_hidden_chars=True,
            )
            == lookup
        ):
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

        if (
            self.body.get_text(
                start,
                (
                    syntax_start := self.body.get_iter_at_offset(
                        start.get_offset() - len(syntax)
                    )
                ),
                include_hidden_chars=True,
            )
            == syntax
        ) and (
            self.body.get_text(
                end,
                (
                    syntax_end := self.body.get_iter_at_offset(
                        end.get_offset() + len(syntax)
                    )
                ),
                include_hidden_chars=True,
            )
            == syntax
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
