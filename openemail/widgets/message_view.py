# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable
from itertools import chain
from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import APP_ID, PREFIX, Notifier, create_task, mail
from openemail.mail import Message

from .attachments import Attachments
from .body import Body
from .profile import ProfileView


@Gtk.Template.from_resource(f"{PREFIX}/message-view.ui")
class MessageView(Adw.Bin):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = "MessageView"

    reply_button: Gtk.Button = Gtk.Template.Child()
    body_view: Body = Gtk.Template.Child()
    attachments: Attachments = Gtk.Template.Child()

    profile_dialog: Adw.Dialog = Gtk.Template.Child()
    profile_view: ProfileView = Gtk.Template.Child()
    confirm_discard_dialog: Adw.AlertDialog = Gtk.Template.Child()

    visible_child_name = GObject.Property(type=str, default="empty")
    app_icon_name = GObject.Property(type=str, default=f"{APP_ID}-symbolic")

    reply = GObject.Signal()
    undo = GObject.Signal(
        flags=GObject.SignalFlags.RUN_FIRST | GObject.SignalFlags.ACTION
    )

    _history: dict[Adw.Toast, Callable[[], Any]]
    _message: Message | None = None

    @GObject.Property(type=Message)
    def message(self) -> Message | None:
        """Get the `Message` that `self` represents."""
        return self._message

    @message.setter
    def message(self, message: Message | None) -> None:
        self._message = message

        if not message:
            self.visible_child_name = "empty"
            return

        self.visible_child_name = "message"
        self.attachments.model = message.attachments

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._history = {}

    @Gtk.Template.Callback()
    def _has_profile(self, *_args: Any) -> bool:
        return self.message and self.message.profile

    @Gtk.Template.Callback()
    def _show_profile_dialog(self, *_args: Any) -> None:
        self.profile_view.profile = self.message.profile
        self.profile_dialog.present(self)

    @Gtk.Template.Callback()
    def _reply(self, *_args: Any) -> None:
        self.emit("reply")

    @Gtk.Template.Callback()
    def _trash(self, *_args: Any) -> None:
        if not self.message:
            return

        (message := self.message).trash()
        self._add_to_undo(_("Message moved to trash"), lambda: message.restore())

    @Gtk.Template.Callback()
    def _restore(self, *_args: Any) -> None:
        if not self.message:
            return

        (message := self.message).restore()
        self._add_to_undo(_("Message restored"), lambda: message.trash())

    @Gtk.Template.Callback()
    def _discard(self, *_args: Any) -> None:
        self.confirm_discard_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_discard(self, *_args: Any) -> None:
        if self.message:
            create_task(self.message.discard())

    @Gtk.Template.Callback()
    def _undo(self, *_args: Any) -> None:
        if not self._history:
            return

        toast, callback = self._history.popitem()
        toast.dismiss()
        callback()

    def _add_to_undo(self, title: str, undo: Callable[[], Any]) -> None:
        toast = Notifier.send(title, lambda *_: self._history.pop(toast, lambda: ...)())  # pyright: ignore[reportUnknownArgumentType]
        self._history[toast] = undo


class ThreadView(Adw.Bin):
    """A view displaying a thread of messages."""

    __gtype_name__ = "ThreadView"

    scrolled_window: Gtk.ScrolledWindow
    box: Gtk.Box

    children: list[MessageView]

    reply = GObject.Signal()

    _message: Message | None = None

    @GObject.Property(type=Message)
    def message(self) -> Message | None:
        """Get the `Message` that `self` represents."""
        return self._message

    @message.setter
    def message(self, message: Message | None) -> None:
        if message == self.message:
            return

        self._message = message

        for child in self.children.copy():
            self.children.remove(child)
            self.box.remove(child)
            child.disconnect_by_func(self._reply)

        self._append(message)

        if not message:
            return

        for current in chain(mail.inbox, mail.outbox):
            if (current == message) or (current.subject_id != message.subject_id):
                continue

            self._append(current)

    def _reply(self, *_args: Any) -> None:
        self.emit("reply")

    def _append(self, message: Message | None) -> None:
        self.children.append(view := MessageView(message=message))
        view.connect("reply", self._reply)
        self.box.append(view)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.children = []
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._append(None)

        self.scrolled_window = Gtk.ScrolledWindow(child=self.box)
        self.props.child = Adw.ToolbarView(content=self.scrolled_window)
