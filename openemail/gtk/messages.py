# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from openemail import PREFIX, Property
from openemail.message import Message

# from .page import Page
from .thread_view import ThreadView

for t in (ThreadView,):
    GObject.type_ensure(t)


@Gtk.Template.from_resource(f"{PREFIX}/message-row.ui")
class MessageRow(Gtk.Box):
    """A row representing a message."""

    __gtype_name__ = __qualname__

    context_menu = Gtk.Template.Child()

    @Property[Message | None](Message)
    def message(self) -> Message | None:
        """The message that `self` represents."""  # noqa: D401
        return self._message

    @message.setter
    def message(self, msg: Message | None):
        self._message = msg
        self.insert_action_group("message", msg)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("row", group := Gio.SimpleActionGroup())

        reply = Gio.SimpleAction.new("reply")
        reply.connect("activate", lambda *_: self._reply())

        template = Gtk.ConstantExpression.new_for_value(self)
        message = Gtk.PropertyExpression.new(MessageRow, template, "message")
        Gtk.PropertyExpression.new(Message, message, "can-reply").bind(reply, "enabled")

        group.add_action(reply)

    def _reply(self):
        ident = GLib.Variant.new_string(self.message.unique_id)
        self.activate_action("compose.reply", ident)

    @Gtk.Template.Callback()
    def _show_context_menu(self, _gesture, _n_press: int, x: float, y: float):
        if self.message.is_draft:
            return

        rect = Gdk.Rectangle()
        rect.x, rect.y = int(x), int(y)
        self.context_menu.props.pointing_to = rect
        self.context_menu.popup()


#         Property.bind(self.folder, "updating", self.page, "loading")

# class Drafts(_Messages):
#     def __init__(self, **kwargs: Any):
#         self.page.model.props.can_unselect = True
#
#         delete_dialog: Adw.AlertDialog = self._get_object("delete_dialog")
#         delete_dialog.connect(
#             "response::delete", lambda *_: store.drafts.delete_all()
#         )
#
#         delete_button: Gtk.Button = self._get_object("delete_button")
#         delete_button.connect("clicked", lambda *_: delete_dialog.present(self))
#         self.page.toolbar_button = delete_button
#
#         self.page.empty_page = self._get_object("no_drafts")
#         Property.bind(self.page.model, "n-items", delete_button, "sensitive")
#
#     def _on_selected(self, selection: Gtk.SingleSelection, *_args):
#         if isinstance(msg := selection.props.selected_item, Message):
#             selection.unselect_all()
#             self.activate_action(
#                 "compose.draft", GLib.Variant.new_string(msg.unique_id)
#             )

# class Trash(_Messages):
#     def __init__(self, **kwargs: Any):
#         empty_dialog: Adw.AlertDialog = self._get_object("empty_dialog")
#         empty_dialog.connect("response::empty", lambda *_: store.empty_trash())
#
#         empty_button: Gtk.Button = self._get_object("empty_button")
#         empty_button.connect("clicked", lambda *_: empty_dialog.present(self))
#         self.page.toolbar_button = empty_button
#
#         self.page.empty_page = self._get_object("empty_trash")
#         Property.bind(self.page.model, "selected-item", self.thread_view, "message")
#         Property.bind(self.page.model, "n-items", empty_button, "sensitive")
#
#         def set_loading(*_args):
#             self.page.loading = store.inbox.updating or store.broadcasts.updating
#
#         store.inbox.connect("notify::updating", set_loading)
#         store.broadcasts.connect("notify::updating", set_loading)
