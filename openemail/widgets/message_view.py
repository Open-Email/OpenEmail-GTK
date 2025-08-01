# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable
from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, Notifier, create_task
from openemail.mail import Message

from .attachments import Attachments
from .body import Body
from .profile import ProfileView


@Gtk.Template.from_resource(f"{PREFIX}/message-view.ui")
class MessageView(Gtk.Box):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = "MessageView"

    reply_button: Gtk.Button = Gtk.Template.Child()
    body_view: Body = Gtk.Template.Child()
    attachments: Attachments = Gtk.Template.Child()

    profile_dialog: Adw.Dialog = Gtk.Template.Child()
    profile_view: ProfileView = Gtk.Template.Child()
    confirm_discard_dialog: Adw.AlertDialog = Gtk.Template.Child()

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

        if message:
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
