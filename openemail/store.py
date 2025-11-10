# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import re
from abc import abstractmethod
from collections import defaultdict
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Callable,
    Coroutine,
    Iterable,
    Iterator,
)
from contextlib import suppress
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Any

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from . import APP_ID, Notifier, Property, core, message, profile, tasks
from .core import client, contacts, model
from .core import drafts as core_drafts
from .core import messages as core_messages
from .core import profile as core_profile
from .core.model import Address, WriteError
from .message import Message
from .profile import Profile

ADDRESS_SPLIT_PATTERN = ",|;| "

settings = Gio.Settings.new(APP_ID)
state_settings = Gio.Settings.new(f"{APP_ID}.State")
secret_service = f"{APP_ID}.Keys"

# TODO: This may not work?
core.data_dir = Path(GLib.get_user_data_dir(), "openemail")
core.cache_dir = Path(GLib.get_user_cache_dir(), "openemail")

profiles = defaultdict[Address, Profile](Profile)


def flatten(*models: GObject.Object) -> Gtk.FlattenListModel:
    """Flatten `models` into a `Gtk.FlattenListModel`.

    All `models` must be `Gio.ListModel` implementations.
    """
    (store := Gio.ListStore.new(Gio.ListModel)).splice(0, 0, models)
    return Gtk.FlattenListModel.new(store)


class DictStore[K, V](GObject.Object, Gio.ListModel):  # pyright: ignore[reportIncompatibleMethodOverride]
    """An implementation of `Gio.ListModel` for storing data in a Python dictionary."""

    __gtype_name__ = __qualname__

    key_for: Callable[[Any], K] = lambda k: k
    default_factory: Callable[[Any], V]

    updating = Property(bool)

    _item_type: type
    _items: dict[K, V]

    @Property(GObject.Object)
    def item_type(self) -> type:
        """The type of items contained in this dict store.

        Items must be subclasses of GObject.
        """
        return self.get_item_type()

    @Property(int)
    def n_items(self) -> int:
        """The number of items contained in this dict store."""
        return self.get_n_items()

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._items = {}
        self.connect("items-changed", lambda *_: self.notify("n-items"))

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
        return self._item_type

    def do_get_n_items(self) -> int:
        """Get the number of items in `self`."""
        return len(self._items)

    async def update(self):
        """Update `self` asynchronously."""
        self.updating = True
        await self._update()
        self.updating = False

    def add(self, item: Any) -> V:  # noqa: ANN401
        """Manually add `item` to `self`.

        Uses `self.__class__.key_for(item)` and `self.__class__.default_factory(item)`
        to get the key and value respectively.

        Note that this will not add it to the underlying data store,
        only the client's version. It may be removed after `update()` is called.
        """
        key = self.__class__.key_for(item)
        if value := self._items.get(key):
            return value

        value = self._items[key] = self.__class__.default_factory(item)
        self.items_changed(len(self._items) - 1, 0, 1)
        return value

    def remove(self, item: K):
        """Remove `item` from `self`.

        Note that this will not remove it from the underlying data store,
        only the client's version. It may be added back after `update()` is called.
        """
        index = list(self._items.keys()).index(item)
        self._items.pop(item)
        self.items_changed(index, 1, 0)

    def clear(self):
        """Remove all items from `self`.

        Note that this will not remove items from the underlying data store,
        only the client's version.
        Cleared items may be added back after `update()` is called.
        """
        n = len(self._items)
        self._items.clear()
        self.items_changed(0, n, 0)

    @abstractmethod
    async def _update(self): ...


class ProfileStore(DictStore[Address, Profile]):
    """An implementation of `Gio.ListModel` for storing profiles."""

    default_factory = Profile.of

    _item_type = Profile

    async def update_profiles(self, *, trust_images: bool = True):
        """Update the profiles of contacts in the user's address book.

        If `trust_images` is set to `False`, profile images will not be loaded.
        """
        for address in (Address(contact.address) for contact in self):
            tasks.create(self._update_profile(address))
            if trust_images:
                tasks.create(self._update_profile_image(address))

    @classmethod
    async def _update_profile(cls, address: Address):
        profile = cls.default_factory(address)
        profile.set_from_profile(core_profile.cached(address))
        profile.set_from_profile(await core_profile.fetch(address))

    @classmethod
    async def _update_profile_image(cls, address: Address):
        profile = cls.default_factory(address)

        with suppress(GLib.Error):
            profile.image = (
                Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
                if (image := core_profile.cached_image(address))
                else None
            )

        try:
            profile.image = (
                Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
                if (image := await core_profile.fetch_image(address))
                else None
            )
        except GLib.Error:
            profile.image = None


class _AddressBook(ProfileStore):
    async def new(self, address: Address, *, receive_broadcasts: bool = True):
        """Add `address` to the user's address book."""
        self.add(address).contact_request = False

        tasks.create(self.update_profiles())
        tasks.create(broadcasts.update())
        tasks.create(inbox.update())

        try:
            await contacts.new(address, receive_broadcasts=receive_broadcasts)
        except WriteError:
            self.remove(address)
            tasks.create(broadcasts.update())
            tasks.create(inbox.update())

            Notifier.send(_("Failed to add contact"))
            raise

    async def delete(self, address: Address):
        """Delete `address` from the user's address book."""
        self.remove(address)
        tasks.create(broadcasts.update())
        tasks.create(inbox.update())

        try:
            await contacts.delete(address)
        except WriteError:
            self.add(address)
            tasks.create(broadcasts.update())
            tasks.create(inbox.update())

            Notifier.send(_("Failed to remove contact"))
            raise

    async def _update(self):
        addresses = set[Address]()

        for address, receives_broadcasts in await contacts.fetch():
            addresses.add(address)
            # TODO: Test if this works
            self.add(address).set_receives_broadcasts(receives_broadcasts)

        for address in self._items.copy():
            if address not in addresses:
                self.remove(address)


address_book = _AddressBook()


class _ContactRequests(ProfileStore):
    async def _update(self):
        for request in (requests := settings.get_strv("contact-requests")):
            try:
                address = Address(request)
            except ValueError:
                continue

            # TODO: Test if this works, both ways
            self.add(address).contact_request = True

        for request in self:
            if request.address not in requests:
                request.contact_request = False
                self.remove(request.address)

        tasks.create(self.update_profiles(trust_images=False))


contact_requests = _ContactRequests()


class People(GObject.Object):
    """The global GObject address store. Mostly useful in a `Gtk.Builder` context."""

    __gtype_name__ = __qualname__

    contact_requests = Property(_ContactRequests, default=contact_requests)
    address_book = Property(_AddressBook, default=address_book)
    all = Property(
        Gtk.FlattenListModel,
        default=flatten(
            globals()["address_book"],
            globals()["contact_requests"],
        ),
    )


class MessageStore(DictStore[str, Message]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    key_for = message.get_unique_id
    default_factory = Message

    _item_type = Message

    def get(self, ident: str) -> Message | None:
        """Get the message with `ident` or `None` if it is not in `self`."""
        return self._items.get(ident)

    async def _update(self):
        idents = set[str]()

        async for msg in self._fetch():
            idents.add(self.add(msg).unique_id)

        for ident in self._items:
            if ident not in idents:
                self.remove(ident)

    @abstractmethod
    def _fetch(self) -> AsyncGenerator[model.Message]: ...

    async def _process_messages(
        self, futures: AsyncIterable[Iterable[model.Message]]
    ) -> AsyncGenerator[model.Message]:
        unread = set[str]()
        async for msgs in futures:
            current_unread = settings.get_strv("unread-messages")

            for msg in msgs:
                if msg.new:
                    unread.add(message.get_unique_id(msg))

                elif message.get_unique_id(msg) in current_unread:
                    msg.new = True

                yield msg

        settings_add("unread-messages", *unread)


class _BroadcastStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        async for msg in self._process_messages(
            await core_messages.fetch_broadcasts(
                address := Address(contact.address),
                exclude=_exclude(address),
            )
            for contact in address_book
            if contact.receive_broadcasts
        ):
            yield msg


broadcasts = _BroadcastStore()


class _InboxStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        known_notifiers = set[Address]()
        other_contacts = {Address(contact.address) for contact in address_book}

        async for notification in core_messages.fetch_notifications():
            if notification.is_expired:
                continue

            if (notifier := notification.notifier) in other_contacts:
                other_contacts.remove(notifier)
                known_notifiers.add(notifier)
                continue

            if notifier.host_part in settings.get_strv("trusted-domains"):
                await address_book.new(notifier)
                known_notifiers.add(notifier)
                continue

            settings_add("contact-requests", notifier)

        async for msg in self._process_messages(
            (
                await core_messages.fetch_link_messages(
                    address, exclude=_exclude(address)
                )
                for address in chain(known_notifiers, other_contacts)
            ),
        ):
            yield msg


inbox = _InboxStore()


class _SentStore(MessageStore):
    default_factory = partial(Message, can_mark_unread=False)

    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for msg in await core_messages.fetch_sent(_exclude(client.user.address)):
            msg.new = False  # New sent messages should be marked read automatically
            yield msg


sent = _SentStore()


class _OutboxStore(MessageStore):
    filter = Gtk.CustomFilter.new(lambda msg: msg.unique_id not in outbox._items)
    default_factory = partial(
        Message,
        can_discard=True,
        can_trash=False,
        can_mark_unread=False,
    )

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.connect("items-changed", self._on_items_changed)

    def _on_items_changed(self, _list, _pos, removed: int, added: int):
        self.filter.changed(
            Gtk.FilterChange.MORE_STRICT
            if added and (not removed)
            else Gtk.FilterChange.LESS_STRICT
            if removed and (not added)
            else Gtk.FilterChange.DIFFERENT
        )

    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for msg in await core_messages.fetch_outbox():
            msg.new = False  # New outbox messages should be marked read automatically
            yield msg


outbox = _OutboxStore()


class _DraftStore(MessageStore):
    def save(
        self,
        ident: str | None = None,
        readers: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        subject_id: str | None = None,
        broadcast: bool = False,
    ):
        """Save a draft to disk for future use.

        `ident` can be used to update a specific draft,
        by default, a new ID is generated.
        """
        readers_list = list[Address]()
        if readers:
            for reader in re.split(ADDRESS_SPLIT_PATTERN, readers):
                try:
                    readers_list.append(Address(reader))
                except ValueError:  # noqa: PERF203
                    continue

        draft = partial(
            model.DraftMessage,
            readers=readers_list,
            subject=subject or "",
            body=body,
            subject_id=subject_id,
            broadcast=broadcast,
        )

        core_drafts.save(draft(ident=ident) if ident else draft())
        self.clear()  # TODO
        tasks.create(self.update())

    def delete(self, ident: str):
        """Delete a draft saved using `save()`."""
        core_drafts.delete(ident)
        self.remove(f"{client.user.address.host_part} {ident}")

    def delete_all(self):
        """Delete all drafts saved using `save()`."""
        core_drafts.delete_all()
        self.clear()

    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for msg in tuple(core_drafts.load()):
            yield msg


drafts = _DraftStore()


async def sync(*, periodic: bool = False):
    """Populate the app's content by fetching the user's data."""
    Notifier().syncing = True

    if periodic:
        interval = settings.get_uint("sync-interval")
        GLib.timeout_add_seconds(interval or 60, tasks.create, sync(periodic=True))

        # The user chose manual sync, check again in a minute
        if not interval:
            return

    # Assume that nobody is logged in, skip sync for now
    if not settings.get_string("address"):
        return

    broadcasts.updating = True
    inbox.updating = True
    outbox.updating = True
    sent.updating = True

    await address_book.update()

    task_set: set[Coroutine[Any, Any, Any]] = {
        profile.refresh(),
        address_book.update_profiles(),
        contact_requests.update(),
        broadcasts.update(),
        inbox.update(),
        outbox.update(),
        sent.update(),
        drafts.update(),
    }

    def done(task: Coroutine[Any, Any, Any]):
        task_set.discard(task)
        if not task_set:
            Notifier().syncing = False

    for task in task_set:
        tasks.create(task, lambda _, t=task: done(t))

    settings.connect(
        "changed::contact-requests",
        lambda *_: tasks.create(contact_requests.update()),
    )


def empty_trash():
    """Empty the user's trash."""
    for msg in tuple(m for m in chain(inbox, broadcasts, sent) if m.trashed):
        msg.delete()


def settings_add(key: str, *items: str):
    """Add `items` to a strv settings `key`."""
    value = settings.get_strv(key)
    settings.set_strv(key, (*value, *(i for i in items if i not in value)))


def settings_discard(key: str, *items: str):
    """Discard `items` from a strv settings `key`."""
    value = settings.get_strv(key)
    for item in items:
        with suppress(ValueError):
            value.remove(item)

    settings.set_strv(key, value)


def _exclude(address: Address) -> tuple[str, ...]:
    return tuple(
        split[1]
        for ident in settings.get_strv("deleted-messages")
        if (split := ident.split(" "))[0] == address.host_part
    )
