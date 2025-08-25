# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from re import Match
from typing import Any

from gi.repository import GLib, GObject, Gtk, Pango

MAX_LINES = 5
MAX_CHARS = 100

MARKDOWN_PATTERNS = (
    (r"(?m)^(?=>)[(?<!\\)> ]*(.*)$", "blockquote"),
    (r"(?m)^(?:(?=>)[(?<!\\)> ]*)?(?<!\\)#+ (.*)$", "heading"),
    (r"(?<!\\)~~(.+?)(?<!\\)~~", "strikethrough"),
    (r"(?<!\*)(?<!\\)\*(.+?)(?<!\\)\*", "italic"),
    (r"(?<!\\)\*\*(.+?)(?<!\\)\*\*", "bold"),
    (r"(?<!\\)\*\*\*(.+?)(?<!\\)\*\*\*", "bold italic"),
    (r"(?<!\\)(\\)[>#~*]", "escape"),
)


class Body(Gtk.TextView):
    """A widget for displaying a message's body with Markdown support."""

    __gtype_name__ = "Body"

    summary = GObject.Property(type=bool, default=False)

    @GObject.Property(type=str)
    def text(self) -> str | None:
        """The message's formatted body."""
        return self.props.buffer.props.text

    @text.setter
    def text(self, text: str | None):
        text = text or ""

        if self.summary:
            text = (
                "\n".join(lines)
                if len(lines := tuple(line for line in text.split("\n") if line))
                <= MAX_LINES
                else "\n".join(lines[:5]) + "…"
            )

        buffer = self.props.buffer
        buffer.remove_all_tags(buffer.get_start_iter(), buffer.get_end_iter())
        if not self.props.editable:
            buffer.props.text = (
                text
                if not self.summary
                else summary
                if len(summary := text.replace("\n", " ")) <= MAX_CHARS
                else summary[:100] + "…"
            )

        for pattern, name in MARKDOWN_PATTERNS:
            for match in re.finditer(pattern, text):
                self._on_match(match, name)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.add_css_class("inline")

        create_tag = self.props.buffer.create_tag
        create_tag("none")
        create_tag("invisible", invisible=True)
        create_tag("blockquote", foreground="#3584e4", weight=500)
        create_tag("heading 1", weight=700, scale=1.6)
        create_tag("heading 2", weight=700, scale=1.5)
        create_tag("heading 3", weight=700, scale=1.4)
        create_tag("heading 4", weight=700, scale=1.3)
        create_tag("heading 5", weight=700, scale=1.2)
        create_tag("heading 6", weight=700, scale=1.1)
        create_tag("strikethrough", strikethrough=True)
        create_tag("italic", style=Pango.Style.ITALIC)
        create_tag("bold", weight=700, style=Pango.Style.NORMAL)
        create_tag("bold italic", style=Pango.Style.ITALIC)
        create_tag("escape", invisible=True)

        self.connect("map", self._resize)
        self.connect("notify::editable", self._on_editable_changed)
        self.notify("editable")

    def _on_match(self, match: Match[str], name: str):
        start, end, group = match.start, match.end, match.group

        if (not self.props.editable) and (start(1) - start() == len(group())):
            self._apply("invisible", start(), end())
            return

        self._apply(self._get_tag(match, name), start(), end())

        if not self.props.editable:
            self._apply("invisible", start(), start(1))
            self._apply("invisible", end(1), end())

    def _get_tag(self, match: Match[str], name: str) -> str:
        match name:
            case "escape" if self.props.editable:
                return "none"
            case "heading" if self.summary:
                return "bold"
            case "heading":
                level_match = re.search(r"#{1,6}", match.group())
                return f"heading {len(level_match.group()) if level_match else 6}"
            case _:
                return name

    def _apply(self, name: str, start: int, end: int):
        get_iter = self.props.buffer.get_iter_at_offset
        self.props.buffer.apply_tag_by_name(name, get_iter(start), get_iter(end))

    def _on_editable_changed(self, *_args):
        if self.get_editable():
            self.props.buffer.connect("changed", self._on_edited)
        else:
            self.props.buffer.disconnect_by_func(self._on_edited)

    def _on_edited(self, *_args):
        self.text = self.props.buffer.props.text

    def _resize(self, *_args):
        """HACK: Fix for some nasty behavior TextView has with height calculations."""
        for t in 10, 20, 30:
            GLib.timeout_add(t, self.queue_resize)
