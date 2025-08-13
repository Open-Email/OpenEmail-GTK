# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
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
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Any

from gi.repository import Gdk, Gio, GLib, GObject

from .asyncio import create_task
from .configuration import APP_ID
from .core import client, model
from .core.client import WriteError
from .core.model import Address
from .message import Message, get_ident
from .notifier import Notifier
from .profile import Profile, refresh

ADDRESS_SPLIT_PATTERN = ",|;| "

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

    def __init__(self, **kwargs: Any):
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

    async def update(self):
        """Update `self` asynchronously."""
        self.updating = True
        await self._update()
        self.updating = False

    def add(self, item: Any):  # noqa: ANN401
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

    item_type = Profile
    default_factory = Profile.of

    async def update_profiles(self, *, trust_images: bool = True):
        """Update the profiles of contacts in the user's address book.

        If `trust_images` is set to `False`, profile images will not be loaded.
        """
        for address in (Address(contact.address) for contact in self):
            create_task(self._update_profile(address))
            if trust_images:
                create_task(self._update_profile_image(address))

    @staticmethod
    async def _update_profile(address: Address):
        Profile.of(address).set_from_profile(await client.fetch_profile(address))

    @staticmethod
    async def _update_profile_image(address: Address):
        try:
            Profile.of(address).image = (
                Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
                if (image := await client.fetch_profile_image(address))
                else None
            )
        except GLib.Error:
            Profile.of(address).image = None


class _AddressBook(ProfileStore):
    """An implementation of `Gio.ListModel` for storing contacts."""

    async def new(self, address: Address, *, receive_broadcasts: bool = True):
        """Add `address` to the user's address book."""
        Profile.of(address).contact_request = False
        self.add(address)

        create_task(self.update_profiles())
        create_task(broadcasts.update())
        create_task(inbox.update())

        try:
            await client.new_contact(address, receive_broadcasts=receive_broadcasts)
        except WriteError:
            self.remove(address)
            create_task(broadcasts.update())
            create_task(inbox.update())

            Notifier.send(_("Failed to add contact"))
            raise

    async def delete(self, address: Address):
        """Delete `address` from the user's address book."""
        self.remove(address)
        create_task(broadcasts.update())
        create_task(inbox.update())

        try:
            await client.delete_contact(address)
        except WriteError:
            self.add(address)
            create_task(broadcasts.update())
            create_task(inbox.update())

            Notifier.send(_("Failed to remove contact"))
            raise

    async def _update(self):
        contacts = set[Address]()

        for contact, receives_broadcasts in await client.fetch_contacts():
            Profile.of(contact).set_receives_broadcasts(receives_broadcasts)
            contacts.add(contact)
            self.add(contact)

        for address in self._items.copy():
            if address not in contacts:
                self.remove(address)


class _ContactRequests(ProfileStore):
    """An implementation of `Gio.ListModel` for storing contact requests."""

    async def _update(self):
        for request in (requests := settings.get_strv("contact-requests")):
            try:
                address = Address(request)
            except ValueError:
                continue

            Profile.of(address).contact_request = True
            self.add(address)

        for request in self:
            if request.address not in requests:
                request.contact_request = False
                self.remove(request.address)

        create_task(self.update_profiles(trust_images=False))


class MessageStore(DictStore[str, Message]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    item_type = Message
    key_for = get_ident
    default_factory = Message

    async def _update(self):
        idents = set[str]()

        async for msg in self._fetch():
            ident = get_ident(msg)

            idents.add(ident)
            if ident in self._items:
                continue

            self._items[ident] = Message(msg)
            self.items_changed(len(self._items) - 1, 0, 1)

        removed = 0
        for index, ident in enumerate(self._items.copy()):
            if ident in idents:
                continue

            self._items.pop(ident)
            self.items_changed(index - removed, 1, 0)
            removed += 1

    @abstractmethod
    def _fetch(self) -> AsyncGenerator[model.Message]: ...

    async def _process_messages(
        self, futures: AsyncIterable[Iterable[model.Message]]
    ) -> AsyncGenerator[model.Message]:
        unread = set[str]()
        async for messages in futures:
            current_unread = settings.get_strv("unread-messages")

            for msg in messages:
                if msg.new:
                    unread.add(get_ident(msg))

                elif get_ident(msg) in current_unread:
                    msg.new = True

                yield msg

        settings.set_strv(
            "unread-messages",
            tuple(set(settings.get_strv("unread-messages")) | unread),
        )


class _BroadcastStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        deleted = settings.get_strv("deleted-messages")
        async for msg in self._process_messages(
            await client.fetch_broadcasts(
                address := Address(contact.address),
                exclude=tuple(
                    split[1]
                    for ident in deleted
                    if (split := ident.split(" "))[0] == address.host_part
                ),
            )
            for contact in address_book
            if contact.receive_broadcasts
        ):
            yield msg


class _InboxStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        known_notifiers = set[Address]()
        other_contacts = {Address(contact.address) for contact in address_book}

        async for notification in client.fetch_notifications():
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

            if str(notifier) in (current := settings.get_strv("contact-requests")):
                continue

            settings.set_strv("contact-requests", [*current, str(notifier)])

        deleted = settings.get_strv("deleted-messages")
        async for msg in self._process_messages(
            (
                await client.fetch_link_messages(
                    contact,
                    exclude=tuple(
                        split[1]
                        for ident in deleted
                        if (split := ident.split(" "))[0] == contact.host_part
                    ),
                )
                for contact in chain(known_notifiers, other_contacts)
            ),
        ):
            yield msg


class _OutboxStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for msg in await client.fetch_outbox():
            msg.new = False  # New outbox messages should be marked read
            yield msg


class _DraftStore(MessageStore):
    def save(
        self,
        ident: str | None = None,
        readers: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        reply: str | None = None,
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
            client.DraftMessage,
            readers=readers_list,
            subject=subject or "",
            body=body,
            subject_id=reply,
        )

        client.save_draft(draft(ident=ident) if ident else draft())
        self.clear()  # TODO
        create_task(self.update())

    def delete(self, ident: str):
        """Delete a draft saved using `save()`."""
        client.delete_draft(ident)
        self.remove(ident)

    def delete_all(self):
        """Delete all drafts saved using `save()`."""
        client.delete_all_drafts()
        self.clear()

    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for msg in tuple(client.load_drafts()):
            yield msg


async def sync(*, periodic: bool = False):
    """Populate the app's content by fetching the user's data."""
    Notifier().syncing = True

    if periodic:
        interval = settings.get_uint("sync-interval")
        GLib.timeout_add_seconds(interval or 60, create_task, sync(periodic=True))

        # The user chose manual sync, check again in a minute
        if not interval:
            return

    # Assume that nobody is logged in, skip sync for now
    if not settings.get_string("address"):
        return

    broadcasts.updating = True
    inbox.updating = True
    outbox.updating = True

    await address_book.update()

    tasks: set[Coroutine[Any, Any, Any]] = {
        refresh(),
        address_book.update_profiles(),
        contact_requests.update(),
        broadcasts.update(),
        inbox.update(),
        outbox.update(),
        drafts.update(),
    }

    def done(task: Coroutine[Any, Any, Any]):
        tasks.discard(task)
        if not tasks:
            Notifier().syncing = False

    for task in tasks:
        create_task(task, lambda _, t=task: done(t))

    settings.connect(
        "changed::contact-requests",
        lambda *_: create_task(contact_requests.update()),
    )


def empty_trash():
    """Empty the user's trash."""
    for msg in tuple(m for m in chain(inbox, broadcasts) if m.trashed):
        msg.delete()


profiles: defaultdict[Address, Profile] = defaultdict(Profile)
address_book = _AddressBook()
contact_requests = _ContactRequests()

broadcasts = _BroadcastStore()
inbox = _InboxStore()
outbox = _OutboxStore()
drafts = _DraftStore()
