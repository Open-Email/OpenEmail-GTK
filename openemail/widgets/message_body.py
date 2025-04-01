# message_body.py
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

from re import compile, search
from typing import Any

from gi.repository import GLib, GObject, Gtk, Pango


class MailMessageBody(Gtk.TextView):
    """A widget for displaying a message's (optionally editable) body with Markdown support."""

    __gtype_name__ = "MailMessageBody"

    summary = GObject.Property(type=bool, default=False)

    @GObject.Property(type=str)
    def text(self) -> str | None:
        """Get the message's formatted body."""
        (buffer := self.get_buffer()).get_text(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
            include_hidden_chars=True,
        )

    @text.setter
    def text(self, text: str) -> None:
        if self.summary:
            text = (
                "\n".join(lines)
                if len(lines := tuple(line for line in text.split("\n") if line)) <= 5
                else "\n".join(lines[:5]) + "…"
            )

        (buffer := self.get_buffer()).remove_all_tags(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
        )

        if not self.get_editable():
            buffer.set_text(text.replace("\n", " ") if self.summary else text)

        for name, pattern in {
            "blockquote": r"(?m)^(?=>)[(?<!\\)> ]*(.*)$",
            "heading": r"(?m)^(?:(?=>)[(?<!\\)> ]*)?(?<!\\)#+ (.*)$",
            "strikethrough": r"(?<!\\)~~(.+?)(?<!\\)~~",
            "italic": r"(?<!\\)\*(.+?)(?<!\\)\*",
            "bold": r"(?<!\\)\*\*(.+?)(?<!\\)\*\*",
            "bold italic": r"(?<!\\)\*\*\*(.+?)(?<!\\)\*\*\*",
            "escape": r"(?<!\\)(\\)[>#~*]",
        }.items():
            for match in compile(pattern).finditer(text):
                if (not self.get_editable()) and (
                    match.start(1) - match.start() == len(match.group())
                ):
                    buffer.apply_tag_by_name(
                        "invisible",
                        buffer.get_iter_at_offset(match.start()),
                        buffer.get_iter_at_offset(match.end()),
                    )
                    continue

                buffer.apply_tag_by_name(
                    "bold"
                    if self.summary
                    else "heading "
                    + str(
                        len(m.group())
                        if (m := search(r"(#{1,6})", match.group()))
                        else 6
                    )
                    if name == "heading"
                    else "none"
                    if ((name == "escape") and self.get_editable())
                    else name,
                    buffer.get_iter_at_offset(match.start()),
                    buffer.get_iter_at_offset(match.end()),
                )

                if self.get_editable():
                    continue

                buffer.apply_tag_by_name(
                    "invisible",
                    buffer.get_iter_at_offset(match.start()),
                    buffer.get_iter_at_offset(match.start(1)),
                )
                buffer.apply_tag_by_name(
                    "invisible",
                    buffer.get_iter_at_offset(match.end(1)),
                    buffer.get_iter_at_offset(match.end()),
                )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.add_css_class("inline")

        buffer = self.get_buffer()
        buffer.create_tag("none")
        buffer.create_tag("invisible", invisible=True)
        buffer.create_tag("blockquote", foreground="#3584e4", weight=500)
        buffer.create_tag("heading 1", weight=700, scale=1.6)
        buffer.create_tag("heading 2", weight=700, scale=1.5)
        buffer.create_tag("heading 3", weight=700, scale=1.4)
        buffer.create_tag("heading 4", weight=700, scale=1.3)
        buffer.create_tag("heading 5", weight=700, scale=1.2)
        buffer.create_tag("heading 6", weight=700, scale=1.1)
        buffer.create_tag("strikethrough", strikethrough=True)
        buffer.create_tag("italic", style=Pango.Style.ITALIC)
        buffer.create_tag("bold", weight=700, style=Pango.Style.NORMAL)
        buffer.create_tag("bold italic", style=Pango.Style.ITALIC)
        buffer.create_tag("escape", invisible=True)

        def edited(*_args: Any) -> None:
            self.text = buffer.get_text(
                buffer.get_start_iter(),
                buffer.get_end_iter(),
                include_hidden_chars=True,
            )

        def editable_changed(*_args: Any) -> None:
            if self.get_editable():
                buffer.connect("changed", edited)
            else:
                buffer.disconnect_by_func(edited)

        self.connect("notify::editable", editable_changed)
        editable_changed()

        # HACK: Fix for a nasty GTK bug I haven't been able to diagnose... In the future
        # if after removing this the layout of the sidebar doesn't break, it's safe to remove.
        #
        # PS: It probably won't be, "Nobody wants to work on TextView."
        self.connect("map", lambda *_: GLib.timeout_add(10, self.queue_resize))
