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

from gi.repository import Adw, GObject, Gtk, Pango


class MailMessageBody(Adw.Bin):
    """A widget ideal for displaying a message's body with Markdown support."""

    __gtype_name__ = "MailMessageBody"

    label: Gtk.Label

    _text: str | None = None
    _summary: bool = False

    @GObject.Property(type=str)
    def text(self) -> str | None:
        """Get the formatted message body."""
        return self._text

    @text.setter
    def text(self, text: str | None) -> None:
        if not text:
            self.label.set_attributes(None)
            self._text = None
            return

        if self.summary:
            if len(lines := tuple(line for line in text.split("\n") if line)) <= 5:
                text = "\n".join(lines)
            else:
                text = "\n".join(lines[:5]) + "…"

        attr_list = Pango.AttrList.new()
        patterns = {
            "blockquote": rb"(?m)^(?=>)[(?<!\\)> ]*(.*)$",
            "heading": rb"(?m)^(?:(?=>)[(?<!\\)> ]*)?(?<!\\)#+ (.*)$",
            "strikethrough": rb"(?<!\\)~~(.+?)(?<!\\)~~",
            "italic": rb"(?<!\\)\*(.+?)(?<!\\)\*",
            "bold": rb"(?<!\\)\*\*(.+?)(?<!\\)\*\*",
            "bold italic": rb"(?<!\\)\*\*\*(.+?)(?<!\\)\*\*\*",
            "escape": rb"(?<!\\)(\\)[>#~*]",
        }

        for name, pattern in patterns.items():
            for match in compile(pattern).finditer(text.encode("utf-8")):
                if match.start(1) - match.start() == len(match.group()):
                    transparent = Pango.attr_foreground_alpha_new(1)
                    transparent.start_index, transparent.end_index = match.span()
                    attr_list.insert(transparent)
                    continue

                attrs = []
                match name:
                    case "blockquote":
                        attrs.append(Pango.attr_foreground_new(13621, 33924, 58596))
                        attrs.append(Pango.attr_weight_new(Pango.Weight.MEDIUM))

                    case "heading":
                        attrs.append(Pango.attr_weight_new(Pango.Weight.BOLD))

                        if (not self.summary) and (
                            m := search(rb"(#{1,6})", match.group())
                        ):
                            attrs.append(
                                Pango.attr_scale_new(1 + ((7 - len(m.group())) * 0.1))
                            )

                    case "strikethrough":
                        attrs.append(Pango.attr_strikethrough_new(True))

                    case "italic":
                        attrs.append(Pango.attr_style_new(Pango.Style.ITALIC))

                    case "bold":
                        attrs.append(Pango.attr_weight_new(Pango.Weight.BOLD))
                        attrs.append(Pango.attr_style_new(Pango.Style.NORMAL))

                    case "bold italic":
                        attrs.append(Pango.attr_style_new(Pango.Style.ITALIC))

                    case "escape":
                        attrs.append(Pango.attr_scale_new(0))

                for attr in attrs:
                    attr.start_index, attr.end_index = match.span(1)
                    attr_list.insert(attr)

                start_syntax = Pango.attr_scale_new(0)
                end_syntax = Pango.attr_scale_new(0)

                start_syntax.start_index, end_syntax.end_index = match.span()
                start_syntax.end_index, end_syntax.start_index = match.span(1)

                attr_list.insert(start_syntax)
                attr_list.insert(end_syntax)

        if self.summary:
            text = text.replace("\n", " ")

        self.label.set_attributes(attr_list)
        self._text = text

    @GObject.Property(type=bool, default=False)
    def summary(self) -> bool:
        """Get whether or not to display the full contents or just the first few lines."""
        return self._summary

    @summary.setter
    def summary(self, summary: bool) -> None:
        self._summary = summary

        self.label.set_selectable(not summary)
        self.label.set_lines(3 if summary else -1)
        self.label.set_ellipsize(
            Pango.EllipsizeMode.END if summary else Pango.EllipsizeMode.NONE
        )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.label = Gtk.Label(
            halign=Gtk.Align.START,
            hexpand=True,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            selectable=True,
        )

        self.set_child(self.label)
        self.bind_property("text", self.label, "label")
