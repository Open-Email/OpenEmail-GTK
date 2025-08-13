# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from itertools import chain
from typing import Any

from gi.repository import Adw, GLib, GObject, Gtk

import openemail as app
from openemail import APP_ID, Message

from .message_view import MessageView


class ThreadView(Adw.Bin):
    """A view displaying a thread of messages."""

    __gtype_name__ = "ThreadView"

    toolbar_view: Adw.ToolbarView
    scrolled_window: Gtk.ScrolledWindow
    viewport: Gtk.Viewport
    box: Gtk.ListBox

    children: list[MessageView]

    reply = GObject.Signal(arg_types=(Message,))

    _message: Message | None = None

    @GObject.Property(type=Message)
    def message(self) -> Message | None:
        """The `Message` that `self` represents."""
        return self._message

    @message.setter
    def message(self, message: Message | None):
        self._message = message

        self.box.remove_all()
        for child in self.children.copy():
            self.children.remove(child)
            child.disconnect_by_func(self._reply)

        if message:
            self.box.remove_css_class("background")
            self.add_css_class("view")

        else:
            status_page = Adw.StatusPage(icon_name=f"{APP_ID}-symbolic")
            status_page.add_css_class("compact")
            status_page.add_css_class("dimmed")
            self.box.set_placeholder(Gtk.WindowHandle(child=status_page))

            self.remove_css_class("view")
            self.box.add_css_class("background")

            return

        row = self._append(message)

        for current in chain(app.inbox, app.outbox):
            if (current == message) or (current.subject_id != message.subject_id):
                continue

            self._append(current)

        GLib.timeout_add(100, self.viewport.scroll_to, row)

    def _reply(self, view: MessageView, *_args):
        self.emit("reply", view.message)

    def _append(self, message: Message | None) -> Gtk.ListBoxRow:
        view = MessageView(message=message)
        view.connect("reply", self._reply)
        self.children.append(view)

        row = Gtk.ListBoxRow(focusable=False, activatable=False, child=view)
        self.box.append(row)
        return row

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.box.add_css_class("background")
        self.box.set_sort_func(
            lambda a, b: b.props.child.message.unix - a.props.child.message.unix  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        )

        self.box.set_header_func(
            lambda row, before: row.set_header(  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                Gtk.Separator(margin_bottom=12, margin_start=18, margin_end=18)
                if before
                else None
            )
        )

        self.children = []
        self.message = None

        self.viewport = Gtk.Viewport(child=self.box)
        self.scrolled_window = Gtk.ScrolledWindow(child=self.viewport)
        self.toolbar_view = Adw.ToolbarView(content=self.scrolled_window)
        self.toolbar_view.add_top_bar(Adw.HeaderBar(show_title=False))
        self.props.child = self.toolbar_view
