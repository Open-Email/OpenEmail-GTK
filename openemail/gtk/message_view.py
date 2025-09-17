# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable
from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, Notifier, Property, tasks
from openemail.message import Message

from .attachments import Attachments
from .body import Body
from .profile_view import ProfileView

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/message-view.ui")
class MessageView(Gtk.Box):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = "MessageView"

    reply_button: Gtk.Button = child
    body_view: Body = child
    attachments: Attachments = child

    profile_dialog: Adw.Dialog = child
    profile_view: ProfileView = child
    confirm_discard_dialog: Adw.AlertDialog = child

    reply = GObject.Signal()
    undo = GObject.Signal(flags=GObject.SignalFlags.ACTION)

    _history: dict[Adw.Toast, Callable[[], Any]]
    _message: Message | None = None

    @Property(Message)
    def message(self) -> Message | None:
        """The `Message` that `self` represents."""
        return self._message

    @message.setter
    def message(self, message: Message | None):
        self._message = message

        if message:
            self.attachments.model = message.attachments

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._history = {}

    @Gtk.Template.Callback()
    def _show_profile_dialog(self, *_args):
        self.profile_view.profile = self.message.profile
        self.profile_dialog.present(self)

    @Gtk.Template.Callback()
    def _reply(self, *_args):
        self.emit("reply")

    @Gtk.Template.Callback()
    def _trash(self, *_args):
        if not self.message:
            return

        (message := self.message).trash()
        self._add_to_undo(_("Message moved to trash"), lambda: message.restore())

    @Gtk.Template.Callback()
    def _restore(self, *_args):
        if self.message:
            (message := self.message).restore()
            self._add_to_undo(_("Message restored"), lambda: message.trash())

    @Gtk.Template.Callback()
    def _discard(self, *_args):
        self.confirm_discard_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_discard(self, *_args):
        if self.message:
            tasks.create(self.message.discard())

    @Gtk.Template.Callback()
    def _undo(self, *_args):
        if not self._history:
            return

        toast, callback = self._history.popitem()
        toast.dismiss()
        callback()

    def _add_to_undo(self, title: str, undo: Callable[[], Any]):
        toast = Notifier.send(title, lambda *_: self._history.pop(toast, lambda: ...)())
        self._history[toast] = undo
