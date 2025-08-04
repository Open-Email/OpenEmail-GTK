# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from abc import abstractmethod
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from gi.repository import Gio, GLib, GObject

from openemail.core import client

from . import APP_ID

settings = Gio.Settings.new(APP_ID)
state_settings = Gio.Settings.new(f"{APP_ID}.State")
secret_service = f"{APP_ID}.Keys"
log_file = Path(GLib.get_user_state_dir(), "openemail.log")
client.data_dir = Path(GLib.get_user_data_dir(), "openemail")


class DictStore[K, V](GObject.Object, Gio.ListModel):  # pyright: ignore[reportIncompatibleMethodOverride]
    """An implementation of `Gio.ListModel` for storing data in a Python dictionary."""

    item_type: type

    key_for: Callable[[Any], K] = lambda k: k
    default_factory: Callable[[Any], V]

    updating = GObject.Property(type=bool, default=False)

    _items: dict[K, V]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._items = {}

    def __iter__(self) -> Iterator[V]:  # pyright: ignore[reportIncompatibleMethodOverride]
        return super().__iter__()  # pyright: ignore[reportReturnType]

    def do_get_item(self, position: int) -> V | None:
        """Get the item at `position`.

        If `position` is greater than the number of items in `self`, `None` is returned.
        """
        try:
            return tuple(self._items.values())[position]
        except IndexError:
            return None

    def do_get_item_type(self) -> type:
        """Get the type of the items in `self`."""
        return self.item_type

    def do_get_n_items(self) -> int:
        """Get the number of items in `self`."""
        return len(self._items)

    async def update(self) -> None:
        """Update `self` asynchronously."""
        self.updating = True
        await self._update()
        self.updating = False

    def add(self, item: Any) -> None:
        """Manually add `item` to `self`.

        Uses `self.__class__.key_for(item)` and `self.__class__.default_factory(item)`
        to get the key and value respectively.

        Note that this will not add it to the underlying data store,
        only the client's version. It may be removed after `update()` is called.
        """
        key = self.__class__.key_for(item)
        if key in self._items:
            return

        self._items[key] = self.__class__.default_factory(item)
        self.items_changed(len(self._items) - 1, 0, 1)

    def remove(self, item: K) -> None:
        """Remove `item` from `self`.

        Note that this will not remove it from the underlying data store,
        only the client's version. It may be added back after `update()` is called.
        """
        index = list(self._items.keys()).index(item)
        self._items.pop(item)
        self.items_changed(index, 1, 0)

    def clear(self) -> None:
        """Remove all items from `self`.

        Note that this will not remove items from the underlying data store,
        only the client's version.
        Cleared items may be added back after `update()` is called.
        """
        n = len(self._items)
        self._items.clear()
        self.items_changed(0, n, 0)

    @abstractmethod
    async def _update(self) -> None: ...
