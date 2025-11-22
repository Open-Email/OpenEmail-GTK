# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from openemail import APP_ID, PREFIX, Property, store
from openemail.message import Message

from .attachments import Attachments
from .body import Body
from .profile_view import ProfileView

child = Gtk.Template.Child()

for t in Attachments, Body:
    GObject.type_ensure(t)


class ToolbarItem(GObject.Object):
    """An item for in a toolbar."""

    __gtype_name__ = __qualname__

    action_name = GObject.Property(type=str)
    label = GObject.Property(type=str)
    icon_name = GObject.Property(type=str)


class Toolbar(Gtk.Box, Gtk.Buildable):
    """A container for actions."""

    __gtype_name__ = __qualname__

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.add_css_class("toolbar")
        self.add_css_class("card")

    def do_add_child(self, _builder, child: GObject.Object, _type):
        """Add a child to `self`."""
        if not isinstance(child, ToolbarItem):
            raise TypeError

        button = Gtk.Button(
            action_name=child.action_name,
            tooltip_text=child.label,
            icon_name=child.icon_name,
        )
        Property.bind(button, "sensitive", button, "visible")
        self.append(button)


@Gtk.Template.from_resource(f"{PREFIX}/message-view.ui")
class MessageView(Gtk.Box):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = __qualname__

    message = Property(Message)

    profile_dialog: Adw.Dialog = child
    profile_view: ProfileView = child

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("message", self.message)
        self.insert_action_group("message-view", group := Gio.SimpleActionGroup())

        reply = Gio.SimpleAction.new("reply")
        reply.connect("activate", lambda *_: self._reply())
        Property.bind(self.message, "can-reply", reply, "enabled")

        group.add_action(reply)

    def _reply(self):
        ident = GLib.Variant.new_string(self.message.unique_id)
        self.activate_action("compose.reply", ident)

    @Gtk.Template.Callback()
    def _show_profile_dialog(self, *_args):
        self.profile_view.profile = self.message.profile
        self.profile_dialog.present(self)


@Gtk.Template.from_resource(f"{PREFIX}/thread-view.ui")
class ThreadView(Adw.Bin):
    """A view displaying a thread of messages."""

    __gtype_name__ = __qualname__

    box: Gtk.ListBox = child
    viewport: Gtk.Viewport = child
    sort_model: Gtk.SortListModel = child

    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")
    message = Property[Message | None](Message)
    subject_id = Property(str)
    model = Property(
        Gio.ListModel,
        default=store.flatten(
            store.inbox,
            store.outbox,
            store.broadcasts,
            Gtk.FilterListModel.new(store.sent, store.outbox.filter),
        ),
    )

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
        row = Gtk.ListBoxRow(activatable=False, child=MessageView(message=item))  # pyright: ignore[reportCallIssue]
        self._rows[item] = row
        return row

    def _scroll_to(self, msg: Message, /):
        if self.message != msg:
            return

        row = self._rows[msg]
        self.viewport.scroll_to(row)

        row.add_css_class("selected-message")
        GLib.timeout_add_seconds(1, row.remove_css_class, "selected-message")
