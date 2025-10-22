# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo
# SPDX-FileContributor: Jamie Gravendeel

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import TYPE_CHECKING, Any, cast

from gi._gtktemplate import CallThing
from gi.repository import Gio, Gtk

if TYPE_CHECKING:
    from asyncio import Task


def create(
    coro: Coroutine[Any, Any, Any],
    callback: Callable[[bool], Any] | None = None,
):
    """Execute a coroutine in a task.

    Calls `callback` on finish with `True` if no exceptions were raised
    and `False` otherwise.
    """
    if not (app := Gio.Application.get_default()):
        msg = "tasks.create() called before Application finished initializing"
        raise RuntimeError(msg)

    task = cast("Task[Any]", app.create_asyncio_task(coro))  # pyright: ignore[reportAttributeAccessIssue]
    task.add_done_callback(
        lambda task: callback(not task.exception()) if callback else None
    )


def callback[**P](func: Callable[P, Coroutine[Any, Any, Any]]) -> CallThing:
    """Create an async `Gtk.Template.Callback`."""

    @Gtk.Template.Callback()
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        create(func(*args, **kwargs))

    return wrapper
