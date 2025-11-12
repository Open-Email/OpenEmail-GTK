# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from collections.abc import Callable
from typing import Any

from gi.repository import Adw, GLib, GObject, Gtk

import openemail as app
from openemail import PREFIX, Property, store, tasks
from openemail.message import Message

from .attachments import Attachments
from .body import Body
from .profile_view import ProfileView

child = Gtk.Template.Child()

for t in Attachments, Body:
    GObject.type_ensure(t)


@Gtk.Template.from_resource(f"{PREFIX}/message-view.ui")
class MessageView(Gtk.Box):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = __qualname__

    message = Property(Message)

    profile_dialog: Adw.Dialog = child
    profile_view: ProfileView = child
    confirm_discard_dialog: Adw.AlertDialog = child

    undo = GObject.Signal(flags=GObject.SignalFlags.ACTION)

    _history: dict[Adw.Toast, Callable[[], Any]]

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._history = {}

    @Gtk.Template.Callback()
    def _can_mark_unread(self, _obj, can_mark_unread: bool, new: bool) -> bool:
        return can_mark_unread and (not new)

    @Gtk.Template.Callback()
    def _string_to_variant(self, _obj, string: str) -> GLib.Variant:
        return GLib.Variant.new_string(string)

    @Gtk.Template.Callback()
    def _show_profile_dialog(self, *_args):
        self.profile_view.profile = self.message.profile
        self.profile_dialog.present(self)

    @Gtk.Template.Callback()
    def _read(self, *_args):
        self.message.new = False
        store.settings_discard("unread-messages", self.message.unique_id)

    @Gtk.Template.Callback()
    def _unread(self, *_args):
        self.message.new = True
        store.settings_add("unread-messages", self.message.unique_id)

    @Gtk.Template.Callback()
    def _trash(self, *_args):
        (msg := self.message).trash()
        self._add_to_undo(_("Message moved to trash"), lambda: msg.restore())

    @Gtk.Template.Callback()
    def _restore(self, *_args):
        (msg := self.message).restore()
        self._add_to_undo(_("Message restored"), lambda: msg.trash())

    @Gtk.Template.Callback()
    def _discard(self, *_args):
        self.confirm_discard_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_discard(self, *_args):
        tasks.create(self.message.discard())

    @Gtk.Template.Callback()
    def _undo(self, *_args):
        if not self._history:
            return

        toast, callback = self._history.popitem()
        toast.dismiss()
        callback()

    def _add_to_undo(self, title: str, undo: Callable[[], Any]):
        toast = app.notifier.send(
            title, lambda *_: self._history.pop(toast, lambda: ...)()
        )
        self._history[toast] = undo
