# store.py
#
# Authors: kramo
# Copyright 2025 Mercata Sagl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later


import asyncio
from abc import abstractmethod
from collections import defaultdict
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    Callable,
    Generic,
    NamedTuple,
    TypeVar,
)

from gi.repository import Gdk, Gio, GLib, GObject

from openemail.core.network import (
    fetch_broadcasts,
    fetch_contacts,
    fetch_link_messages,
    fetch_profile,
    fetch_profile_image,
)

from .core.message import Message
from .core.user import Address, Profile
from .shared import settings, user

T = TypeVar("T")
U = TypeVar("U")

_loading = 0


def is_loading() -> bool:
    """Check whether or not an update is currently ongoing."""
    return bool(_loading)


class DictStore(GObject.Object, Gio.ListModel, Generic[T, U]):  # type: ignore
    """An implementation of `Gio.ListModel` for storing data in a Python dictionary."""

    _items: dict[T, U]
    item_type: type

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._items = {}

    def do_get_item(self, position: int) -> U | None:
        """Get the item at `position`. If `position` is greater than the number of items in `self`, `None` is returned."""
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

    @abstractmethod
    async def update(self) -> None:
        """Update `self` asynchronously using `self.fetch()`."""

    def clear(self) -> None:
        """Remove all messages from `self`."""
        n = len(self._items)
        self._items.clear()
        self.items_changed(0, n, 0)


class MailMessage(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "MailMessage"

    message: Message | None = None

    name = GObject.Property(type=str)
    date = GObject.Property(type=str)
    subject = GObject.Property(type=str)
    body = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    @property
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if not self.message:
            return False

        return self.message.envelope.message_id in settings.get_strv(
            "trashed-message-ids"
        )

    def __init__(self, message: Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if message:
            self.set_from_message(message)

    def set_from_message(self, message: Message) -> None:
        """Update properties of the row from `message`."""
        self.message = message

        self.date = message.envelope.date.strftime("%x")
        self.subject = message.envelope.subject
        self.body = message.body

        if self._name_binding:
            self._name_binding.unbind()
        self._name_binding = profiles[message.envelope.author].bind_property(
            "name", self, "name", GObject.BindingFlags.SYNC_CREATE
        )

        if self._image_binding:
            self._image_binding.unbind()
        self._image_binding = profiles[message.envelope.author].bind_property(
            "image", self, "profile-image", GObject.BindingFlags.SYNC_CREATE
        )


class MailMessageStore(DictStore[str, MailMessage]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    fetch: Callable[[], AsyncIterable[Message]]

    def __init__(
        self, fetch: Callable[[], AsyncIterable[Message]], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.item_type = MailMessage

        self.fetch = fetch

    async def update(self) -> None:
        """Update `self` asynchronously using `self.fetch()`."""
        global _loading
        _loading += 1

        message_ids: set[str] = set()

        async for message in self.fetch():
            message_ids.add(message_id := message.envelope.message_id)
            if message_id in self._items:
                continue

            self._items[message_id] = MailMessage(message)
            self.items_changed(len(self._items) - 1, 0, 1)

        removed = 0
        for index, message_id in enumerate(self._items.copy()):
            if message_id in message_ids:
                continue

            self._items.pop(message_id)
            self.items_changed(index - removed, 1, 0)
            removed += 1

        _loading -= 1


def trash_message(message_id: str) -> None:
    """Move the message associated with `message_id` to the trash."""
    settings.set_strv(
        "trashed-message-ids",
        settings.get_strv("trashed-message-ids") + [message_id],
    )


def restore_message(message_id: str) -> None:
    """Restore the message associated with `message_id` from the trash."""
    try:
        (trashed := settings.get_strv("trashed-message-ids")).remove(message_id)
    except ValueError:
        return

    settings.set_strv("trashed-message-ids", trashed)


async def __fetch_broadcasts() -> AsyncGenerator[Message]:
    async for messages in asyncio.as_completed(
        fetch_broadcasts(user, Address(contact.address))  # type: ignore
        for contact in address_book
    ):
        for message in await messages:
            yield message


async def __fetch_inbox() -> AsyncGenerator[Message]:
    async for messages in asyncio.as_completed(
        fetch_link_messages(user, Address(contact.address))  # type: ignore
        for contact in address_book
    ):
        for message in await messages:
            yield message


async def __fetch_outbox() -> AsyncGenerator[Message]:
    async for messages in asyncio.as_completed(
        (
            fetch_link_messages(user, user.address),
            fetch_broadcasts(user, user.address),
        )
    ):
        for message in await messages:
            yield message


broadcasts = MailMessageStore(__fetch_broadcasts)
inbox = MailMessageStore(__fetch_inbox)
outbox = MailMessageStore(__fetch_outbox)


class MailProfile(GObject.Object):
    """A GObject representation of a user profile."""

    __gtype_name__ = "MailProfile"

    has_name = GObject.Property(type=bool, default=False)
    image = GObject.Property(type=Gdk.Paintable)

    _profile: Profile | None = None
    _address: str | None = None
    _name: str | None = None

    @property
    def profile(self) -> Profile | None:
        """The profile of the user."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None) -> None:
        self._profile = profile

        if not profile:
            self.image = None
            return

        self.address = str(profile.address)
        self.name = str(profile.required["name"])

    @GObject.Property(type=str)
    def address(self) -> str | None:
        """Get the user's Mail/HTTPS address."""
        return self._address

    @address.setter
    def address(self, address: str) -> None:
        self._address = address

        if not self.name:
            self.name = address

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the user's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name
        self.has_name = name != self.address


class MailContactsStore(DictStore[Address, MailProfile]):
    """An implementation of `Gio.ListModel` for storing contacts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.item_type = MailProfile

    async def update(self) -> None:
        """Update `self` asynchronously."""
        global _loading
        _loading += 1

        contacts: set[Address] = set()

        for contact in await fetch_contacts(user):
            contacts.add(contact)

            if contact in self._items:
                continue

            profiles[contact] = self._items[contact] = MailProfile(address=str(contact))
            self.items_changed(len(self._items) - 1, 0, 1)

        removed = 0
        for index, address in enumerate(self._items.copy()):
            if address in contacts:
                continue

            self._items.pop(address)
            self.items_changed(index - removed, 1, 0)
            removed += 1

        _loading -= 1


profiles: defaultdict[Address, MailProfile] = defaultdict(MailProfile)
address_book = MailContactsStore()


async def update_user_profile() -> None:
    """Update the profile of the user by fetching new data remotely."""
    global _loading
    _loading += 1

    if profile := await fetch_profile(user.address):
        user.public_signing_key = profile.required["signing-key"].value
        if key := profile.optional.get("encryption-key"):
            user.public_encryption_key = key.value

    profiles[user.address].profile = profile

    try:
        profiles[user.address].image = Gdk.Texture.new_from_bytes(
            GLib.Bytes.new(await fetch_profile_image(user.address))
        )
    except GLib.Error:
        profiles[user.address].image = None

    _loading -= 1


async def update_profiles() -> None:
    """Update the profiles for contacts in the user's address book by fetching new data remotely."""
    global _loading
    _loading += 1

    async def update_profile(address: Address) -> None:
        profiles[address].profile = await fetch_profile(address)

    async def update_profile_image(address: Address) -> None:
        try:
            profiles[address].image = (
                Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
                if (image := await fetch_profile_image(address))
                else None
            )
        except GLib.Error:
            profiles[address].image = None

    await asyncio.gather(
        *(update_profile(Address(contact.address)) for contact in address_book),  # type: ignore
        *(update_profile_image(Address(contact.address)) for contact in address_book),  # type: ignore
    )

    _loading += 1


class ProfileCategory(NamedTuple):
    """A category of profile fields."""

    ident: str
    name: str


profile_categories: dict[ProfileCategory, dict[str, str]] = {
    ProfileCategory("general", _("General")): {
        "status": _("Status"),
        "about": _("About"),
    },
    ProfileCategory("personal", _("Personal")): {
        "gender": _("Gender"),
        "relationship-status": _("Relationship Status"),
        "birthday": _("Birthday"),
        "education": _("Education"),
        "languages": _("Languages"),
        "places-lived": _("Places Lived"),
        "notes": _("Notes"),
    },
    ProfileCategory("work", _("Work")): {
        "work": _("Work"),
        "organization": _("Organization"),
        "department": _("Department"),
        "job-title": _("Job Title"),
    },
    ProfileCategory("interests", _("Interests")): {
        "interests": _("Interests"),
        "books": _("Books"),
        "movies": _("Movies"),
        "music": _("Music"),
        "sports": _("Sports"),
    },
    ProfileCategory("contacts", _("Contacts")): {
        "website": _("Website"),
        "location": _("Location"),
        "mailing-address": _("Mailing Address"),
        "phone": _("Phone"),
    },
}
