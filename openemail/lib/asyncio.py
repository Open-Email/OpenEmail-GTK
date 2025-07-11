# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

from gi.repository import Gio

if TYPE_CHECKING:
    from asyncio import Task


def create_task(
    coro: Coroutine[Any, Any, Any],
    callback: Callable[[bool], Any] | None = None,
) -> None:
    """Execute a coroutine in a task.

    Calls `callback` on finish with `True` if no exceptions were raised
    and `False` otherwise.
    """
    if not (app := Gio.Application.get_default()):
        msg = "create_task() called before Application finished initializing"
        raise RuntimeError(msg)

    task = cast("Task[Any]", app.create_asyncio_task(coro))  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    task.add_done_callback(
        lambda task: callback(not task.exception()) if callback else None
    )
