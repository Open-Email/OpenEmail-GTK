# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from openemail import APP_ID, PREFIX, Property, store
from openemail.message import Message

from .message_view import MessageView

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/thread-view.ui")
class ThreadView(Adw.Bin):
    """A view displaying a thread of messages."""

    __gtype_name__ = "ThreadView"

    box: Gtk.ListBox = child
    viewport: Gtk.Viewport = child
    sort_model: Gtk.SortListModel = child

    message = Property[Message | None](Message)
    subject_id = Property(str)
    model = Property(Gio.ListModel, default=store.messages)
    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")

    reply = GObject.Signal(arg_types=(Message,))

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.box.set_header_func(
            lambda row, before: row.set_header(
                Gtk.Separator(
                    margin_top=6,
                    margin_bottom=6,
                    margin_start=18,
                    margin_end=18,
                )
                if before
                else None
            )
        )

        self._rows = dict[Message, Gtk.ListBoxRow]()
        self.box.bind_model(self.sort_model, self._create_widget)

        self.connect("notify::message", self._on_message_changed)
        self.notify("message")

    def _on_message_changed(self, *_args):
        if not self.message:
            self._rows.clear()

        self.subject_id = (
            # "No ID" here is not proper, but I'm not sure what would be better.
            # This needs to be done because the default behavior of StringFilter is to
            # allow everything on ""/null instead of denying and you can't change this.
            msg.subject_id if (msg := self.message) and msg.subject_id else "No ID"
        )

        (self.add_css_class if msg else self.remove_css_class)("view")
        (self.box.remove_css_class if msg else self.box.add_css_class)("background")

        if self.message and (len(self.sort_model) > 1):
            GLib.timeout_add(100, self._scroll_to, self.message)

    def _create_widget(self, item: Message) -> Gtk.Widget:
        view = MessageView(message=item)
        view.connect("reply", lambda *_: self.emit("reply", view.message))
        row = Gtk.ListBoxRow(activatable=False, child=view)

        self._rows[item] = row
        return row

    def _scroll_to(self, msg: Message):
        if self.message != msg:
            return

        row = self._rows[msg]
        self.viewport.scroll_to(row)

        row.add_css_class("selected-message")
        GLib.timeout_add_seconds(1, row.remove_css_class, "selected-message")
