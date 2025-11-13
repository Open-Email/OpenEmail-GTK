# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from collections.abc import Callable
from typing import Any, ClassVar

from gi.repository import Adw, GObject

from ._property import Property


class _Notifier(GObject.Object):
    """Used for sending user-facing information throughout the application."""

    sending = Property(bool)
    syncing = Property(bool)
    offline = Property(bool)

    _send = GObject.Signal("send", arg_types=(Adw.Toast,))

    _history: ClassVar[dict[Adw.Toast, Callable[..., Any]]] = {}

    def send(self, title: str, *, undo: Callable[..., Any] | None = None):
        """Emit the `Notifier::send` signal with a toast from `title` and `undo`.

        `undo` is called on `Adw.Toast::button-clicked`.
        """
        toast = Adw.Toast(title=title, priority=Adw.ToastPriority.HIGH)

        if undo:
            toast.props.button_label = _("Undo")
            toast.connect("button-clicked", lambda toast: self.undo(toast))
            self._history[toast] = undo

        self.emit("send", toast)

    def undo(self, toast: Adw.Toast | None = None):
        """Undo the most recent item in history or a function of a toast."""
        if toast:
            self._history.pop(toast)()
            return

        try:
            toast, func = self._history.popitem()
        except KeyError:
            return

        toast.dismiss()
        func()


notifier = _Notifier()
