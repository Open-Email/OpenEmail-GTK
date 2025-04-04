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

from gi.repository import Adw, Gtk

from openemail.core.network import send_message
from openemail.core.user import Address
from openemail.shared import PREFIX, run_task, user
from openemail.store import outbox
from openemail.widgets.form import MailForm
from openemail.widgets.message_body import MailMessageBody


@Gtk.Template(resource_path=f"{PREFIX}/gtk/compose-dialog.ui")
class MailComposeDialog(Adw.Dialog):
    """A page listing a subset of the user's messages."""

    __gtype_name__ = "MailComposeDialog"

    broadcast_switch: Gtk.Switch = Gtk.Template.Child()
    readers: Gtk.Text = Gtk.Template.Child()
    subject: Gtk.Text = Gtk.Template.Child()
    body_view: MailMessageBody = Gtk.Template.Child()
    compose_form: MailForm = Gtk.Template.Child()

    body: Gtk.TextBuffer
    subject_id: str | None = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.body = self.body_view.get_buffer()

    @Gtk.Template.Callback()
    def _new_message(self, *_args: Any) -> None:
        self.subject_id = None
        self.compose_form.reset()
        self.broadcast_switch.set_active(False)

        self.present(self)
        self.readers.grab_focus()

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

        run_task(
            send_message(
                user,
                readers,
                self.subject.get_text(),
                self.body.get_text(
                    self.body.get_start_iter(),
                    self.body.get_end_iter(),
                    False,
                ),
                self.subject_id,
            ),
            lambda: run_task(outbox.update()),
        )

        self.subject_id = None
        self.force_close()

    @Gtk.Template.Callback()
    def _reveal_readers(self, revealer: Gtk.Revealer, *_args: Any) -> None:
        self.compose_form.address_lists = Gtk.StringList.new(
            ("readers",) if revealer.get_reveal_child() else ()
        )

    @Gtk.Template.Callback()
    def _format_bold(self, *_args: Any) -> None:
        self.__format_inline("**")

    @Gtk.Template.Callback()
    def _format_italic(self, *_args: Any) -> None:
        self.__format_inline("*")

    @Gtk.Template.Callback()
    def _format_strikethrough(self, *_args: Any) -> None:
        self.__format_inline("~~")

    @Gtk.Template.Callback()
    def _format_heading(self, *_args: Any) -> None:
        self.__format_line("#")

    @Gtk.Template.Callback()
    def _format_quote(self, *_args: Any) -> None:
        self.__format_line(">", toggle=True)

    def __format_line(self, syntax: str, toggle: bool = False) -> None:
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

    def __format_inline(self, syntax: str) -> None:
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
