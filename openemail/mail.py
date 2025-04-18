# mail.py
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
from functools import wraps
from itertools import chain
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Coroutine,
    Generic,
    Iterable,
    NamedTuple,
    TypeVar,
)

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from openemail import notifier, run_task, settings

from .core import client
from .core.client import WriteError as WriteError
from .core.client import cache_dir as cache_dir
from .core.client import data_dir as data_dir
from .core.client import is_writing as is_writing
from .core.client import user as user
from .core.model import Address, Message, Profile

_syncing = 0


def is_syncing() -> bool:
    """Check whether or not a sync operation is currently ongoing."""
    return bool(_syncing)


def _syncs(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Coroutine[Any, Any, Any]:
        global _syncing
        _syncing += 1

        try:
            result = await func(*args, **kwargs)
        except Exception as error:
            _syncing -= 1
            raise error

        _syncing -= 1
        return result

    return wrapper


def try_auth(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
) -> None:
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth() -> None:
        if not client.try_auth():
            raise ValueError

    def failure() -> None:
        notifier.send(_("Authentication failed"))

        if on_failure:
            on_failure()

    run_task(auth(), lambda success: on_success if success else failure)


async def update_profile(values: dict[str, str]) -> None:
    """Update the user's public profile with `values`."""
    try:
        await client.update_profile(values)
    except WriteError as error:
        notifier.send(_("Failed to update profile"))
        raise error

    await update_user_profile()


async def update_profile_image(pixbuf: GdkPixbuf.Pixbuf) -> None:
    """Upload `pixbuf` to be used as the user's profile image."""
    if (width := pixbuf.get_width()) > (height := pixbuf.get_height()):
        if width > 800:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=int(width * (800 / height)),
                    dest_height=800,
                    interp_type=GdkPixbuf.InterpType.BILINEAR,
                )
                or pixbuf
            )

            width = pixbuf.get_width()
            height = pixbuf.get_height()

        pixbuf = pixbuf.new_subpixbuf(
            src_x=int((width - height) / 2),
            src_y=0,
            width=height,
            height=height,
        )
    else:
        if height > 800:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=800,
                    dest_height=int(height * (800 / width)),
                    interp_type=GdkPixbuf.InterpType.BILINEAR,
                )
                or pixbuf
            )

            width = pixbuf.get_width()
            height = pixbuf.get_height()

        if height > width:
            pixbuf = pixbuf.new_subpixbuf(
                src_x=0,
                src_y=int((height - width) / 2),
                height=width,
                width=width,
            )

    try:
        success, data = pixbuf.save_to_bufferv(
            type="jpeg",
            option_keys=("quality",),
            option_values=("80",),
        )
    except GLib.Error as error:
        notifier.send(_("Failed to update profile image"))
        raise WriteError from error

    if not success:
        notifier.send(_("Failed to update profile image"))
        raise WriteError

    try:
        await client.update_profile_image(data)
    except WriteError as error:
        notifier.send(_("Failed to update profile image"))
        raise error

    await update_user_profile()


@_syncs
async def update_user_profile() -> None:
    """Update the profile of the user by fetching new data remotely."""
    if profile := await client.fetch_profile(user.address):
        user.public_signing_key = profile.required["signing-key"].value
        if key := profile.optional.get("encryption-key"):
            user.public_encryption_key = key.value

    profiles[user.address].profile = profile

    try:
        profiles[user.address].image = Gdk.Texture.new_from_bytes(
            GLib.Bytes.new(
                await client.fetch_profile_image(
                    user.address,
                )
            )
        )
    except GLib.Error:
        profiles[user.address].image = None


async def delete_profile_image() -> None:
    """Delete the user's profile image."""
    try:
        await client.delete_profile_image()
    except WriteError as error:
        notifier.send(_("Failed to delete profile image"))
        raise error

    await update_user_profile()


async def send_message(
    readers: Iterable[Address],
    subject: str,
    body: str,
    reply: str | None = None,
    attachments: dict[Gio.File, str] = {},
) -> None:
    """Send `message` to `readers`.

    If `readers` is empty, send a broadcast.

    `reply` is an optional `Subject-ID` of a thread that the message should be part of.

    `attachments` is a dictionary of `Gio.File`s and filenames.
    """
    notifier.send(_("Sending message…"))

    files = {}
    for gfile, name in attachments.items():
        try:
            _success, bytes, _etag = await gfile.load_contents_async()  # type: ignore
        except GLib.Error as error:
            raise WriteError from error

        files[name] = bytes

    try:
        await client.send_message(
            readers,
            subject,
            body,
            reply,
            attachments=files,
        )
    except WriteError as error:
        notifier.send(_("Failed to send message"))
        raise error

    await outbox.update()


async def discard_message(message: Message) -> None:
    """Discard `message` and its children."""
    failed = False

    for msg in [message] + message.children:
        try:
            await client.delete_message(msg.envelope.message_id)
        except WriteError:
            if not failed:
                notifier.send(_("Failed to discard message"))

            failed = True
            continue

    await outbox.update()


def trash_message(message_id: str) -> None:
    """Move the message associated with `message_id` to the trash."""
    settings.set_strv(
        "trashed-messages",
        settings.get_strv("trashed-messages") + [message_id],
    )


def restore_message(message_id: str) -> None:
    """Restore the message associated with `message_id` from the trash."""
    try:
        (trashed := settings.get_strv("trashed-messages")).remove(message_id)
    except ValueError:
        return

    settings.set_strv("trashed-messages", trashed)


T = TypeVar("T")
U = TypeVar("U")


class DictStore(GObject.Object, Gio.ListModel, Generic[T, U]):  # type: ignore
    """An implementation of `Gio.ListModel` for storing data in a Python dictionary."""

    _items: dict[T, U]
    item_type: type

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._items = {}

    def do_get_item(self, position: int) -> U | None:
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

    @abstractmethod
    @_syncs
    async def update(self) -> None:
        """Update `self` asynchronously."""

    def remove(self, item: T) -> None:
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


class MailMessage(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "MailMessage"

    message: Message | None = None

    name = GObject.Property(type=str)
    date = GObject.Property(type=str)
    subject = GObject.Property(type=str)
    body = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    subject_id = GObject.Property(type=str)
    draft_id = GObject.Property(type=int)
    broadcast = GObject.Property(type=bool, default=False)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    @property
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if not self.message:
            return False

        return self.message.envelope.message_id in settings.get_strv("trashed-messages")

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

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.item_type = MailMessage

    @abstractmethod
    async def _fetch(self): ...  # noqa: ANN202

    @_syncs
    async def update(self) -> None:
        """Update `self` asynchronously using `self._fetch()`."""
        message_ids: set[str] = set()

        async for message in self._fetch():  # type: ignore
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


class MailDraftStore(DictStore[int, MailMessage]):
    """An implementation of `Gio.ListModel` for storing drafts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.item_type = MailMessage

    def save(
        self,
        readers: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        reply: str | None = None,
        broadcast: bool = False,
        draft_id: int | None = None,
    ) -> None:
        """Save a draft to disk for future use.

        `draft_id` can be used to update a specific draft, by default, a new ID is generated.
        """
        client.save_message(readers, subject, body, reply, broadcast, draft_id)
        run_task(self.update())

    def delete(self, draft_id: int) -> None:
        """Delete a draft saved by `save_draft()`."""
        client.delete_saved_message(draft_id)
        self.remove(draft_id)

    @_syncs
    async def update(self) -> None:
        """Update `self` by loading the latest drafts."""
        idents: set[int] = set()

        previous = len(self._items)
        self._items.clear()

        for draft in (drafts := tuple(client.load_saved_messages())):
            message = MailMessage()
            (
                message.draft_id,
                message.name,
                message.subject,
                message.body,
                message.subject_id,
                message.broadcast,
            ) = draft

            profiles[user.address].bind_property(
                "image", message, "profile-image", GObject.BindingFlags.SYNC_CREATE
            )

            idents.add(message.draft_id)
            self._items[message.draft_id] = message

        self.items_changed(0, previous, len(drafts))


class MailProfile(GObject.Object):
    """A GObject representation of a user profile."""

    __gtype_name__ = "MailProfile"

    contact_request = GObject.Property(type=bool, default=False)
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


class MailProfileStore(DictStore[Address, MailProfile]):
    """An implementation of `Gio.ListModel` for storing profiles."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.item_type = MailProfile

    def add(self, contact: Address) -> None:
        """Manually add `contact` to `self`.

        Note that this item will be removed after `update()` is called
        and if is not part of the user's remote address book.
        """
        if contact in self._items:
            return

        profiles[contact] = self._items[contact] = MailProfile(address=str(contact))
        self.items_changed(len(self._items) - 1, 0, 1)

    @_syncs
    async def update_profiles(self, trust_images: bool = True) -> None:
        """Update the profiles of contacts in the user's address book.

        If `trust_images` is set to `False`, profile images will not be loaded.
        """
        await asyncio.gather(
            *chain(
                (
                    self.__update_profile(Address(contact.address))  # type: ignore
                    for contact in self
                ),
                (
                    self.__update_profile_image(Address(contact.address))  # type: ignore
                    for contact in self
                )
                if trust_images
                else (),
            ),
        )

    @staticmethod
    async def __update_profile(address: Address) -> None:
        profiles[address].profile = await client.fetch_profile(address)

    @staticmethod
    async def __update_profile_image(address: Address) -> None:
        try:
            profiles[address].image = (
                Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
                if (image := await client.fetch_profile_image(address))
                else None
            )
        except GLib.Error:
            profiles[address].image = None


class MailAddressBook(MailProfileStore):
    """An implementation of `Gio.ListModel` for storing contacts."""

    async def new(self, address: Address) -> None:
        """Add `address` to the user's address book."""
        self.add(address)
        run_task(self.update_profiles())
        run_task(broadcasts.update())
        run_task(inbox.update())

        try:
            await client.new_contact(address)
        except WriteError as error:
            self.remove(address)
            run_task(broadcasts.update())
            run_task(inbox.update())

            notifier.send(_("Failed to add contact"))
            raise error

    async def delete(self, address: Address) -> None:
        """Delete `address` from the user's address book."""
        self.remove(address)
        run_task(broadcasts.update())
        run_task(inbox.update())

        try:
            await client.delete_contact(address)
        except WriteError as error:
            self.add(address)
            run_task(broadcasts.update())
            run_task(inbox.update())

            notifier.send(_("Failed to remove contact"))
            raise error

    @_syncs
    async def update(self) -> None:
        """Update `self` from remote data asynchronously."""
        contacts: set[Address] = set()

        for contact in await client.fetch_contacts():
            contacts.add(contact)
            self.add(contact)

        for index, address in enumerate(self._items.copy()):
            if address not in contacts:
                self.remove(address)


class MailContactRequests(MailProfileStore):
    """An implementation of `Gio.ListModel` for storing contact requests."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        settings.connect(
            "changed::contact-requests",
            lambda *_: run_task(self.update()),
        )
        run_task(self.update())

    @_syncs
    async def update(self) -> None:
        """Update `self` from remote data asynchronously.

        Note that calling this method manually is typically not required
        as updates should happen automatically.
        """
        for request in (requests := settings.get_strv("contact-requests")):
            try:
                self.add(Address(request))
            except ValueError:
                continue

        for request in self:
            if request.address not in requests:  # type: ignore
                self.remove(request.address)  # type: ignore
                continue

            request.contact_request = True  # type: ignore

        run_task(self.update_profiles(trust_images=False))


class _BroadcastStore(MailMessageStore):
    async def _fetch(self) -> AsyncGenerator[Message, None]:  # type: ignore
        async for messages in asyncio.as_completed(
            client.fetch_broadcasts(Address(contact.address))  # type: ignore
            for contact in address_book
        ):
            for message in await messages:
                yield message


class _InboxStore(MailMessageStore):
    async def _fetch(self) -> AsyncGenerator[Message, None]:  # type: ignore
        known_notifiers = set()
        other_contacts = {Address(contact.address) for contact in address_book}  # type: ignore

        async for notification in client.fetch_notifications():
            if notification.is_expired:
                continue

            if notification.notifier in other_contacts:
                other_contacts.discard(notification.notifier)
                known_notifiers.add(notification.notifier)
            else:
                settings.set_strv(
                    "contact-requests",
                    tuple(
                        set(
                            settings.get_strv("contact-requests")
                            + [str(notification.notifier)]
                        )
                    ),
                )

        async for messages in asyncio.as_completed(
            (
                *(client.fetch_link_messages(n) for n in known_notifiers),
                *(client.fetch_link_messages(contact) for contact in other_contacts),
            )
        ):
            for message in await messages:
                yield message


class _OutboxStore(MailMessageStore):
    async def _fetch(self) -> AsyncGenerator[Message, None]:  # type: ignore
        async for messages in asyncio.as_completed(
            (
                client.fetch_link_messages(user.address),
                client.fetch_broadcasts(user.address),
            )
        ):
            for message in await messages:
                yield message


broadcasts = _BroadcastStore()
inbox = _InboxStore()
outbox = _OutboxStore()
drafts = MailDraftStore()

profiles: defaultdict[Address, MailProfile] = defaultdict(MailProfile)
address_book = MailAddressBook()
contact_requests = MailContactRequests()


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
