# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import asyncio
from abc import abstractmethod
from collections import defaultdict, namedtuple
from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Coroutine,
    Iterable,
    Iterator,
)
from dataclasses import fields
from datetime import datetime
from itertools import chain
from shutil import rmtree
from typing import Any, cast

import keyring
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from openemail import notifier, run_task, secret_service, settings

from .core import client, model
from .core.client import WriteError as WriteError
from .core.client import user as user
from .core.crypto import KeyPair as KeyPair
from .core.model import Address as Address
from .core.model import User as User


def try_auth(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
) -> None:
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth() -> None:
        if not await client.try_auth():
            raise ValueError

    def done(success: bool) -> None:
        if success:
            if on_success:
                on_success()
            return

        notifier.send(_("Authentication failed"))

        if on_failure:
            on_failure()

    run_task(auth(), done)


def register(
    on_success: Callable[[], Any] | None = None,
    on_failure: Callable[[], Any] | None = None,
) -> None:
    """Try authenticating and call `on_success` or `on_failure` based on the result."""

    async def auth() -> None:
        if not await client.register():
            raise ValueError

    def done(success: bool) -> None:
        if success:
            if on_success:
                on_success()
            return

        notifier.send(_("Registration failed, try another address"))

        if on_failure:
            on_failure()

    run_task(auth(), done)


syncing = False
_first_sync = True


async def sync(periodic: bool = False) -> None:
    """Populate the app's content by fetching the user's data."""
    global syncing
    global _first_sync

    if periodic and (interval := settings.get_uint("sync-interval")):
        GLib.timeout_add_seconds(interval or 60, sync, True)

        # The user chose manual sync, check again in a minute
        if not interval:
            return

        # Assume that nobody is logged in, skip sync for now
        if not settings.get_string("address"):
            return

    if not _first_sync:
        if syncing:
            notifier.send(_("Sync already running"))
            return

        notifier.send(_("Syncing…"))

    syncing = True
    _first_sync = False

    broadcasts.updating = True
    inbox.updating = True
    outbox.updating = True

    await address_book.update()

    tasks: set[Coroutine[Any, Any, Any]] = {
        update_user_profile(),
        address_book.update_profiles(),
        broadcasts.update(),
        inbox.update(),
        outbox.update(),
        drafts.update(),
    }

    def done(task: Coroutine[Any, Any, Any]) -> None:
        global syncing

        tasks.discard(task)
        syncing = bool(tasks)

    for task in tasks:
        run_task(task, lambda _, t=task: done(t))


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
    if (width := pixbuf.props.width) > (height := pixbuf.props.height):
        if width > 800:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=int(width * (800 / height)),
                    dest_height=800,
                    interp_type=GdkPixbuf.InterpType.BILINEAR,
                )
                or pixbuf
            )

            width = pixbuf.props.width
            height = pixbuf.props.height

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

            width = pixbuf.props.width
            height = pixbuf.props.height

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


async def update_user_profile() -> None:
    """Update the profile of the user by fetching new data remotely."""
    user_profile.updating = True

    user_profile.profile = await client.fetch_profile(user.address)
    if user_profile.profile:
        user.signing_keys.public = user_profile.profile.signing_key

        if user_profile.profile.encryption_key:
            user.encryption_keys.public = user_profile.profile.encryption_key

    try:
        user_profile.image = Gdk.Texture.new_from_bytes(
            GLib.Bytes.new(await client.fetch_profile_image(user.address))
        )
    except GLib.Error:
        user_profile.image = None

    Profile.of(user.address).image = user_profile.image
    Profile.of(user.address).profile = user_profile.profile
    user_profile.updating = False


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
            _success, data, _etag = await cast(
                Awaitable[tuple[bool, bytes, str]], gfile.load_contents_async()
            )
        except GLib.Error as error:
            raise WriteError from error

        files[name] = data

    try:
        await client.send_message(readers, subject, body, reply, attachments=files)
    except WriteError as error:
        notifier.send(_("Failed to send message"))
        raise error

    await outbox.update()


def empty_trash() -> None:
    """Empty the user's trash."""
    for store in inbox, broadcasts:
        for message in store:
            if not isinstance(message, Message):
                continue

            if message.message and message.trashed:
                store.delete(message.message.ident)


def log_out() -> None:
    """Remove the user's local account."""
    for profile in _profiles.values():
        profile.profile = None

    _profiles.clear()
    address_book.clear()
    contact_requests.clear()
    broadcasts.clear()
    inbox.clear()
    outbox.clear()

    settings.reset("address")
    settings.reset("sync-interval")
    settings.reset("trusted-domains")
    settings.reset("contact-requests")
    settings.reset("unread-messages")
    settings.reset("trashed-messages")
    settings.reset("deleted-messages")

    keyring.delete_password(secret_service, str(user.address))

    rmtree(client.data_dir, ignore_errors=True)

    for field in fields(User):
        delattr(user, field.name)


async def delete_account() -> None:
    """Permanently delete the user's account."""
    try:
        await client.delete_account()
    except WriteError:
        notifier.send(_("Failed to delete account"))
        return

    log_out()


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


class Profile(GObject.Object):
    """A GObject representation of a user profile."""

    __gtype_name__ = "Profile"

    updating = GObject.Property(type=bool, default=False)
    contact_request = GObject.Property(type=bool, default=False)
    has_name = GObject.Property(type=bool, default=False)

    image = GObject.Property(type=Gdk.Paintable)

    Category = namedtuple("Category", ("ident", "name"))
    categories: dict[Category, dict[str, str]] = {
        Category("general", _("General")): {
            "status": _("Status"),
            "about": _("About"),
        },
        Category("personal", _("Personal")): {
            "gender": _("Gender"),
            "relationship-status": _("Relationship Status"),
            "birthday": _("Birthday"),
            "education": _("Education"),
            "languages": _("Languages"),
            "places-lived": _("Places Lived"),
            "notes": _("Notes"),
        },
        Category("work", _("Work")): {
            "work": _("Work"),
            "organization": _("Organization"),
            "department": _("Department"),
            "job-title": _("Job Title"),
        },
        Category("interests", _("Interests")): {
            "interests": _("Interests"),
            "books": _("Books"),
            "movies": _("Movies"),
            "music": _("Music"),
            "sports": _("Sports"),
        },
        Category("contacts", _("Contact")): {
            "website": _("Website"),
            "location": _("Location"),
            "mailing-address": _("Mailing Address"),
            "phone": _("Phone"),
            "streams": _("Topics"),
        },
        Category("configuration", _("Options")): {
            "public-access": _("People Can Reach Me"),
            "public-links": _("Public Contacts"),
            "last-seen-public": _("Share Presence"),
            "address-expansion": _("Address Expansion"),
        },
    }

    _profile: model.Profile | None = None
    _broadcasts: bool = True
    _address: str | None = None
    _name: str | None = None

    @property
    def profile(self) -> model.Profile | None:
        """Get the `model.Profile` that `self` represents."""
        return self._profile

    @profile.setter
    def profile(self, profile: model.Profile | None) -> None:
        self._profile = profile

        if not profile:
            self.image = None
            return

        self.address = str(profile.address)
        self.name = profile.name

    @GObject.Property(type=bool, default=True)
    def receive_broadcasts(self) -> bool:
        """Whether to receive broadcasts from the owner of the profile.

        See `Profile.set_receives_broadcasts()`.
        """
        return self._broadcasts

    @receive_broadcasts.setter
    def receive_broadcasts(self, receive_broadcasts: bool) -> None:
        if self._broadcasts == receive_broadcasts or (not self.profile):
            return

        self._broadcasts = receive_broadcasts

        run_task(broadcasts.update())
        run_task(
            client.new_contact(
                self.profile.address,
                receive_broadcasts=receive_broadcasts,
            )
        )

    @GObject.Property(type=str)
    def address(self) -> str | None:
        """Get the profile owner's Mail/HTTPS address."""
        return self._address

    @address.setter
    def address(self, address: str) -> None:
        self._address = address

        if not self.name:
            self.name = address

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the profile owner's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name
        self.has_name = name != self.address

    @staticmethod
    def of(address: Address) -> "Profile":
        """Get the profile associated with `address`."""
        (profile := _profiles[address]).address = str(address)
        return profile

    def value_of(self, ident: str) -> Any:
        """Get the value of the field identified by `ident` in `self`."""
        try:
            return getattr(self.profile, ident.replace("-", "_"))
        except AttributeError:
            return None

    def set_receives_broadcasts(self, value: bool) -> None:
        """Use this method to update the local state from remote data.

        Set `Profile.receive_broadcasts` to update the remote state as well.
        """
        if value == self._broadcasts:
            return

        self._broadcasts = value
        self.notify("receive-broadcasts")


class ProfileStore(DictStore[Address, Profile]):
    """An implementation of `Gio.ListModel` for storing profiles."""

    item_type = Profile

    def add(self, contact: Address, *, receives_broadcasts: bool = True) -> None:
        """Manually add `contact` to `self`.

        Note that this item will be removed after `update()` is called
        and if is not part of the user's remote address book.
        """
        if contact in self._items:
            return

        Profile.of(contact).set_receives_broadcasts(receives_broadcasts)
        self._items[contact] = Profile.of(contact)
        self.items_changed(len(self._items) - 1, 0, 1)

    async def update_profiles(self, trust_images: bool = True) -> None:
        """Update the profiles of contacts in the user's address book.

        If `trust_images` is set to `False`, profile images will not be loaded.
        """
        await asyncio.gather(
            *chain(
                (self._update_profile(Address(contact.address)) for contact in self),
                (
                    self._update_profile_image(Address(contact.address))
                    for contact in self
                )
                if trust_images
                else (),
            ),
        )

    @staticmethod
    async def _update_profile(address: Address) -> None:
        Profile.of(address).profile = await client.fetch_profile(address)

    @staticmethod
    async def _update_profile_image(address: Address) -> None:
        try:
            Profile.of(address).image = (
                Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
                if (image := await client.fetch_profile_image(address))
                else None
            )
        except GLib.Error:
            Profile.of(address).image = None


class AddressBook(ProfileStore):
    """An implementation of `Gio.ListModel` for storing contacts."""

    async def new(self, address: Address, *, receive_broadcasts: bool = False) -> None:
        """Add `address` to the user's address book."""
        Profile.of(address).contact_request = False
        self.add(address)

        run_task(self.update_profiles())
        run_task(broadcasts.update())
        run_task(inbox.update())

        try:
            await client.new_contact(address, receive_broadcasts=receive_broadcasts)
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

    async def _update(self) -> None:
        """Update `self` from remote data asynchronously."""
        contacts: set[Address] = set()

        for contact, receives_broadcasts in await client.fetch_contacts():
            contacts.add(contact)
            self.add(contact, receives_broadcasts=receives_broadcasts)

        for index, address in enumerate(self._items.copy()):
            if address not in contacts:
                self.remove(address)


class MailContactRequests(ProfileStore):
    """An implementation of `Gio.ListModel` for storing contact requests."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        settings.connect(
            "changed::contact-requests",
            lambda *_: run_task(self.update()),
        )
        run_task(self.update())

    async def _update(self) -> None:
        """Update `self` from remote data asynchronously.

        Note that calling this method manually is typically not required
        as updates should happen automatically.
        """
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

        run_task(self.update_profiles(trust_images=False))


class Attachment(GObject.Object):
    """An file attached to a Mail/HTTPS message."""

    __gtype_name__ = "Attachment"

    name = GObject.Property(type=str)
    parts: list[model.Message]

    def __init__(self, name: str, parts: list[model.Message], **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.name, self.parts = name, parts

    async def download(self) -> bytes | None:
        """Download and reconstruct `self` from its parts."""
        if not (data := await client.download_attachment(self.parts)):
            notifier.send(_("Failed to download attachment"))
            return None

        return data


class Message(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "Message"

    date = GObject.Property(type=str)
    datetime = GObject.Property(type=str)

    subject = GObject.Property(type=str)
    body = GObject.Property(type=str)
    unread = GObject.Property(type=bool, default=False)

    subject_id = GObject.Property(type=str)
    draft_id = GObject.Property(type=int)
    broadcast = GObject.Property(type=bool, default=False)

    can_reply = GObject.Property(type=bool, default=False)
    author_is_self = GObject.Property(type=bool, default=False)
    can_trash = GObject.Property(type=bool, default=False)
    can_restore = GObject.Property(type=bool, default=False)

    original_author = GObject.Property(type=str)
    different_author = GObject.Property(type=bool, default=False)
    readers = GObject.Property(type=str)
    reader_addresses = GObject.Property(type=str)

    attachments = GObject.Property(type=Gio.ListStore)

    name = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    _message: model.Message | None = None

    @property
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if not self.message:
            return False

        return self.message.ident in settings.get_strv("trashed-messages")

    @property
    def message(self) -> model.Message | None:
        """Get the `model.Message` that `self` represents."""
        return self._message

    @message.setter
    def message(self, message: model.Message | None) -> None:
        self._message = message

        if not message:
            self.unread = False
            self.broadcast = False
            self.can_reply = False
            self.author_is_self = False
            self.can_trash = False
            self.can_restore = False
            self.different_author = False
            return

        self.date = message.date.strftime("%x")
        # Localized date format, time in H:M
        self.datetime = _("{} at {}").format(
            self.date, message.date.astimezone(datetime.now().tzinfo).strftime("%H:%M")
        )

        self.subject = message.subject
        self.body = message.body or ""
        self.unread = message.new

        self.author_is_self = message.author == user.address

        self._update_trashed_state()

        self.original_author = f"{_('Original Author:')} {str(message.original_author)}"
        self.different_author = message.author != message.original_author

        if message.is_broadcast:
            self.readers = _("Broadcast")
        else:
            self.readers = f"{_('Readers:')} {str(user_profile.name)}"
            for reader in message.readers:
                if reader == user.address:
                    continue

                self.readers += f", {Profile.of(reader).name or reader}"

        self.reader_addresses = ", ".join(
            str(reader)
            for reader in list(dict.fromkeys(message.readers + [message.author]))
            if (reader != user.address)
        )

        self.attachments.remove_all()
        for name, parts in message.attachments.items():
            self.attachments.append(Attachment(name, parts))

        if self._name_binding:
            self._name_binding.unbind()

        self._name_binding = Profile.of(message.author).bind_property(
            "name", self, "name", GObject.BindingFlags.SYNC_CREATE
        )

        if self._image_binding:
            self._image_binding.unbind()

        self._image_binding = Profile.of(message.author).bind_property(
            "image", self, "profile-image", GObject.BindingFlags.SYNC_CREATE
        )

    def __init__(self, message: model.Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attachments = Gio.ListStore.new(Attachment)
        self.message = message

    def trash(self) -> None:
        """Move `self` to the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(set(settings.get_strv("trashed-messages")) | {self._message.ident}),
        )

        self._update_trashed_state()

    def restore(self) -> None:
        """Restore `self` from the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(set(settings.get_strv("trashed-messages")) - {self._message.ident}),
        )

        self._update_trashed_state()

    async def discard(self) -> None:
        """Discard `self` and its children."""
        if not self._message:
            return

        outbox.remove(self._message.ident)

        failed = False
        for msg in [self._message] + self._message.children:
            try:
                await client.delete_message(msg.ident)
            except WriteError:
                if not failed:
                    notifier.send(_("Failed to discard message"))

                failed = True
                continue

        await outbox.update()

    def mark_read(self) -> None:
        """Mark a message as read.

        Does nothing if the message is not unread.
        """
        if not self.unread:
            return

        self.unread = False

        if not self.message:
            return

        self.message.new = False
        settings.set_strv(
            "unread-messages",
            tuple(set(settings.get_strv("unread-messages")) - {self.message.ident}),
        )

    def _update_trashed_state(self) -> None:
        self.can_trash = not (self.author_is_self or self.trashed)
        self.can_restore = self.trashed
        self.can_reply = not self.can_restore


class MessageStore(DictStore[str, Message]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    item_type = Message

    def delete(self, ident: str) -> None:
        """Delete the message with `ident`.

        From the user's perspective, this means removing an item from the trash.
        """
        settings.set_strv(
            "deleted-messages",
            tuple(set(settings.get_strv("deleted-messages")) | {ident}),
        )

        if not ((message := self._items.get(ident)) and (parent := message.message)):
            return

        envelopes_dir = (
            client.data_dir
            / "envelopes"
            / parent.author.host_part
            / parent.author.local_part
        )
        messages_dir = (
            client.data_dir
            / "messages"
            / parent.author.host_part
            / parent.author.local_part
        )

        if parent.is_broadcast:
            envelopes_dir /= "broadcasts"
            messages_dir /= "broadcasts"

        for child in [parent] + parent.children:
            (envelopes_dir / f"{child.ident}.json").unlink(missing_ok=True)
            (messages_dir / child.ident).unlink(missing_ok=True)

        self.remove(ident)
        message.restore()

    async def _update(self) -> None:
        """Update `self` asynchronously using `self._fetch()`."""
        idents: set[str] = set()

        async for message in self._fetch():  # type: ignore
            idents.add(message.ident)
            if message.ident in self._items:
                continue

            self._items[message.ident] = Message(message)
            self.items_changed(len(self._items) - 1, 0, 1)

        removed = 0
        for index, ident in enumerate(self._items.copy()):
            if ident in idents:
                continue

            self._items.pop(ident)
            self.items_changed(index - removed, 1, 0)
            removed += 1

    @abstractmethod
    async def _fetch(self) -> ...: ...

    async def _process_messages(
        self, futures: Iterable[Awaitable[Iterable[model.Message]]]
    ) -> AsyncGenerator[model.Message, None]:
        unread = set()
        # TODO: Replace with async for in 3.13, not supported in 3.12
        for messages in asyncio.as_completed(futures):
            # This is async iteration, we don't want a data race
            current_unread = settings.get_strv("unread-messages")

            for message in await messages:
                if message.new:
                    unread.add(message.ident)

                elif message.ident in current_unread:
                    message.new = True

                yield message

        settings.set_strv(
            "unread-messages",
            tuple(set(settings.get_strv("unread-messages")) | unread),
        )


class MailDraftStore(DictStore[int, Message]):
    """An implementation of `Gio.ListModel` for storing drafts."""

    item_type = Message

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
        client.save_draft(readers, subject, body, reply, broadcast, draft_id)
        run_task(self.update())

    def delete(self, draft_id: int) -> None:
        """Delete a draft saved using `save()`."""
        client.delete_draft(draft_id)
        self.remove(draft_id)

    def delete_all(self) -> None:
        """Delete all drafts saved using `save()`."""
        client.delete_all_saved_messages()
        self.clear()

    async def _update(self) -> None:
        """Update `self` by loading the latest drafts."""
        idents: set[int] = set()

        previous = len(self._items)
        self._items.clear()

        for draft in (drafts := tuple(client.load_drafts())):
            message = Message()
            (
                message.draft_id,
                message.name,
                message.subject,
                message.body,
                message.subject_id,
                message.broadcast,
            ) = draft

            user_profile.bind_property(
                "image",
                message,
                "profile-image",
                GObject.BindingFlags.SYNC_CREATE,
            )

            idents.add(message.draft_id)
            self._items[message.draft_id] = message

        self.items_changed(0, previous, len(drafts))


class _BroadcastStore(MessageStore):
    async def _fetch(self) -> ...:
        async for message in self._process_messages(
            client.fetch_broadcasts(
                Address(contact.address),
                exclude=settings.get_strv("deleted-messages"),
            )
            for contact in address_book
            if contact.receive_broadcasts
        ):
            yield message


class _InboxStore(MessageStore):
    async def _fetch(self) -> ...:
        known_notifiers = set()
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

            settings.set_strv("contact-requests", current + [str(notifier)])

        deleted = settings.get_strv("deleted-messages")
        async for message in self._process_messages(
            (
                client.fetch_link_messages(contact, exclude=deleted)
                for contact in chain(known_notifiers, other_contacts)
            ),
        ):
            yield message


class _OutboxStore(MessageStore):
    async def _fetch(self) -> ...:
        for message in await client.fetch_outbox():
            message.new = False  # New outbox messages should be marked read

            yield message


_profiles: defaultdict[Address, Profile] = defaultdict(Profile)
address_book = AddressBook()
contact_requests = MailContactRequests()
user_profile = Profile()

broadcasts = _BroadcastStore()
inbox = _InboxStore()
outbox = _OutboxStore()
drafts = MailDraftStore()

run_task(sync(periodic=True))
