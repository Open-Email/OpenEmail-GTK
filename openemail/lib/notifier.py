# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable
from typing import Any, Self

from gi.repository import Adw, GObject


class Notifier(GObject.Object):
    """Used for sending user-facing information throughout the application."""

    sending = GObject.Property(type=bool, default=False)
    syncing = GObject.Property(type=bool, default=False)

    send_notification = GObject.Signal(name="send", arg_types=(Adw.Toast,))

    _default = None

    def __new__(cls, **kwargs: Any) -> Self:  # noqa: D102
        if not cls._default:
            cls._default = super().__new__(cls, **kwargs)

        return cls._default

    @classmethod
    def send(
        cls, title: str, undo: Callable[[Adw.Toast, Any], Any] | None = None
    ) -> Adw.Toast:
        """Emit the `Notifier::send` signal with a toast from `title` and `undo`.

        `undo` is called on `Adw.Toast::button-clicked`.
        """
        toast = Adw.Toast(title=title, priority=Adw.ToastPriority.HIGH)

        if undo:
            toast.props.button_label = _("Undo")  # pyright: ignore[reportUndefinedVariable]
            toast.connect("button-clicked", undo)

        cls().emit("send", toast)
        return toast
