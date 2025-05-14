# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from abc import abstractmethod
from collections.abc import Iterator
from typing import Any

from gi.repository import Gio, GObject


class DictStore[K, V](GObject.Object, Gio.ListModel):  # type: ignore
    """An implementation of `Gio.ListModel` for storing data in a Python dictionary."""

    item_type: type

    updating = GObject.Property(type=bool, default=False)

    _items: dict[K, V]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._items = {}

    def __iter__(self) -> Iterator[V]:  # type: ignore
        return super().__iter__()  # type: ignore

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
        only the client's version. Cleared items may be added back after `update()` is called.
        """
        n = len(self._items)
        self._items.clear()
        self.items_changed(0, n, 0)

    @abstractmethod
    async def _update(self) -> None: ...
