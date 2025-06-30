# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from typing import Any

from gi.repository import GLib, GObject, Gtk, Pango

MAX_LINES = 5
MAX_CHARS = 100


class Body(Gtk.TextView):
    """A widget for displaying a message's body with Markdown support."""

    __gtype_name__ = "Body"

    summary = GObject.Property(type=bool, default=False)

    @GObject.Property(type=str)
    def text(self) -> str | None:
        """Get the message's formatted body."""
        return self.props.buffer.props.text

    @text.setter
    def text(self, text: str | None) -> None:
        text = text or ""

        if self.summary:
            text = (
                "\n".join(lines)
                if len(lines := tuple(line for line in text.split("\n") if line))
                <= MAX_LINES
                else "\n".join(lines[:5]) + "…"
            )

        (buffer := self.get_buffer()).remove_all_tags(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
        )

        if not self.props.editable:
            buffer.props.text = (
                text
                if not self.summary
                else summary
                if len(summary := text.replace("\n", " ")) <= MAX_CHARS
                else summary[:100] + "…"
            )

        for name, pattern in {
            "blockquote": r"(?m)^(?=>)[(?<!\\)> ]*(.*)$",
            "heading": r"(?m)^(?:(?=>)[(?<!\\)> ]*)?(?<!\\)#+ (.*)$",
            "strikethrough": r"(?<!\\)~~(.+?)(?<!\\)~~",
            "italic": r"(?<!\*)(?<!\\)\*(.+?)(?<!\\)\*",
            "bold": r"(?<!\\)\*\*(.+?)(?<!\\)\*\*",
            "bold italic": r"(?<!\\)\*\*\*(.+?)(?<!\\)\*\*\*",
            "escape": r"(?<!\\)(\\)[>#~*]",
        }.items():
            for match in re.compile(pattern).finditer(text):
                if (not self.props.editable) and (
                    match.start(1) - match.start() == len(match.group())
                ):
                    buffer.apply_tag_by_name(
                        "invisible",
                        buffer.get_iter_at_offset(match.start()),
                        buffer.get_iter_at_offset(match.end()),
                    )
                    continue

                buffer.apply_tag_by_name(
                    "none"
                    if ((name == "escape") and self.props.editable)
                    else name
                    if name != "heading"
                    else "bold"
                    if self.summary
                    else "heading "
                    + str(
                        len(m.group())
                        if (m := re.search(r"(#{1,6})", match.group()))
                        else 6
                    ),
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

        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.add_css_class("inline")

        buffer = self.props.buffer
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
            self.text = buffer.props.text

        def editable_changed(*_args: Any) -> None:
            if self.get_editable():
                buffer.connect("changed", edited)
            else:
                buffer.disconnect_by_func(edited)

        self.connect("notify::editable", editable_changed)
        editable_changed()

        # HACK: Fix for some nasty behavior TextView has with height calculations
        def resize(*_args: Any) -> None:
            GLib.timeout_add(10, self.queue_resize)
            GLib.timeout_add(20, self.queue_resize)
            GLib.timeout_add(30, self.queue_resize)

        self.connect("map", resize)
