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

    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")

    message = Property[Message | None](Message)
    subject_id = Property(str)

    reply = GObject.Signal(arg_types=(Message,))

    _models = Gio.ListStore.new(item_type=Gio.ListModel)
    _models.append(store.inbox)
    _models.append(store.sent)
    _models.append(store.broadcasts)

    model = Property(Gio.ListModel, default=Gtk.FlattenListModel.new(_models))

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.box.set_header_func(
            lambda row, before: row.set_header(
                Gtk.Separator(margin_bottom=12, margin_start=18, margin_end=18)
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

        if self.message:
            GLib.timeout_add(100, self.viewport.scroll_to, self._rows[self.message])

    def _create_widget(self, item: Message) -> Gtk.Widget:
        view = MessageView(message=item)
        view.connect("reply", lambda *_: self.emit("reply", view.message))
        row = Gtk.ListBoxRow(focusable=False, activatable=False, child=view)

        self._rows[item] = row
        return row
