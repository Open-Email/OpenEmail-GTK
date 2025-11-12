# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from collections.abc import Callable
from typing import Any

from gi.repository import Adw, GObject

from ._property import Property


class _Notifier(GObject.Object):
    """Used for sending user-facing information throughout the application."""

    sending = Property(bool)
    syncing = Property(bool)
    offline = Property(bool)

    _send = GObject.Signal("send", arg_types=(Adw.Toast,))

    def send(
        self, title: str, undo: Callable[[Adw.Toast, Any], Any] | None = None
    ) -> Adw.Toast:
        """Emit the `Notifier::send` signal with a toast from `title` and `undo`.

        `undo` is called on `Adw.Toast::button-clicked`.
        """
        toast = Adw.Toast(title=title, priority=Adw.ToastPriority.HIGH)

        if undo:
            toast.props.button_label = _("Undo")
            toast.connect("button-clicked", undo)

        self.emit("send", toast)
        return toast


notifier = _Notifier()
