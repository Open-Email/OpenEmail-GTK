# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import asyncio
from abc import abstractmethod
from collections import defaultdict, namedtuple
from dataclasses import fields
from datetime import datetime
from functools import wraps
from itertools import chain
from shutil import rmtree
from typing import Any, AsyncGenerator, Awaitable, Callable, Coroutine, Iterable

import keyring
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from openemail import notifier, run_task, secret_service, settings

from .core import client
from .core.client import WriteError as WriteError
from .core.client import data_dir as data_dir
from .core.client import user as user
from .core.crypto import KeyPair as KeyPair
from .core.model import Address as Address
from .core.model import Message as Message
from .core.model import Profile as Profile
from .core.model import User as User

_syncing = 0
_writing = 0


def is_syncing() -> bool:
    """Check whether or not a sync operation is currently ongoing."""
    return bool(_syncing)


def is_writing() -> bool:
    """Check whether or not a write operation is currently ongoing."""
    return bool(_writing)


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


def _writes(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Coroutine[Any, Any, Any]:
        global _writing
        _writing += 1

        try:
            result = await func(*args, **kwargs)
        except Exception as error:
            _writing -= 1
            raise error

        _writing -= 1
        return result

    return wrapper


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


@_writes
async def update_profile(values: dict[str, str]) -> None:
    """Update the user's public profile with `values`."""
    try:
        await client.update_profile(values)
    except WriteError as error:
        notifier.send(_("Failed to update profile"))
        raise error

    await update_user_profile()


@_writes
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


@_syncs
async def update_user_profile() -> None:
    """Update the profile of the user by fetching new data remotely."""
    if profile := await client.fetch_profile(user.address):
        user.signing_keys.public = profile.signing_key

        if profile.encryption_key:
            user.encryption_keys.public = profile.encryption_key

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


@_writes
async def delete_profile_image() -> None:
    """Delete the user's profile image."""
    try:
        await client.delete_profile_image()
    except WriteError as error:
        notifier.send(_("Failed to delete profile image"))
        raise error

    await update_user_profile()


async def download_attachment(parts: Iterable[Message]) -> bytes | None:
    """Download and reconstruct an attachment from `parts`."""
    if not (attachment := await client.download_attachment(parts)):
        notifier.send(_("Failed to download attachment"))
        return None

    return attachment


@_writes
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


def empty_trash() -> None:
    """Empty the user's trash."""
    for store in inbox, broadcasts:
        for message in store:
            if not isinstance(message, MailMessage):
                continue

            if message.message and message.trashed:
                store.delete(message.message.ident)


def log_out() -> None:
    """Remove the user's local account."""
    for profile in profiles.values():
        profile.profile = None

    profiles.clear()
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

    rmtree(data_dir, ignore_errors=True)

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

    _items: dict[K, V]
    item_type: type

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._items = {}

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

    @abstractmethod
    @_syncs
    async def update(self) -> None:
        """Update `self` asynchronously."""

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
        self.name = profile.name

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

    item_type = MailProfile

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
                    self._update_profile(Address(contact.address))  # type: ignore
                    for contact in self
                ),
                (
                    self._update_profile_image(Address(contact.address))  # type: ignore
                    for contact in self
                )
                if trust_images
                else (),
            ),
        )

    @staticmethod
    async def _update_profile(address: Address) -> None:
        profiles[address].profile = await client.fetch_profile(address)

    @staticmethod
    async def _update_profile_image(address: Address) -> None:
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

    @_writes
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

    @_writes
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


class MailMessage(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "MailMessage"

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

    attachments: dict[str, list[Message]]

    name = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    _message: Message | None = None

    @property
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if not self.message:
            return False

        return self.message.ident in settings.get_strv("trashed-messages")

    @property
    def message(self) -> Message | None:
        """Get the `model.Message` that `self` represents."""
        return self._message

    @message.setter
    def message(self, message: Message | None) -> None:
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

        self.can_reply = True
        self.author_is_self = message.author == user.address
        self.can_trash = not (self.author_is_self or self.trashed)
        self.can_restore = self.trashed

        self.original_author = f"{_('Original Author:')} {str(message.original_author)}"
        self.different_author = message.author != message.original_author

        if message.is_broadcast:
            self.readers = _("Broadcast")
        else:
            self.readers = f"{_('Readers:')} {str(profiles[user.address].name)}"
            for reader in message.readers:
                if reader == user.address:
                    continue

                self.readers += (
                    f", {profile.name if (profile := profiles.get(reader)) else reader}"
                )

        self.reader_addresses = ", ".join(
            str(reader)
            for reader in list(dict.fromkeys(message.readers + [message.author]))
            if (reader != user.address)
        )

        self.attachments = message.attachments

        if self._name_binding:
            self._name_binding.unbind()

        self._name_binding = profiles[message.author].bind_property(
            "name", self, "name", GObject.BindingFlags.SYNC_CREATE
        )

        if self._image_binding:
            self._image_binding.unbind()

        self._image_binding = profiles[message.author].bind_property(
            "image", self, "profile-image", GObject.BindingFlags.SYNC_CREATE
        )

    def __init__(self, message: Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attachments = {}

        if message:
            self.message = message

    def trash(self) -> None:
        """Move `self` to the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(set(settings.get_strv("trashed-messages")) | {self._message.ident}),
        )

    def restore(self) -> None:
        """Restore `self` from the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(set(settings.get_strv("trashed-messages")) - {self._message.ident}),
        )

    @_writes
    async def discard(self) -> None:
        """Discard `self` and its children."""
        if not self._message:
            return

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


class MailMessageStore(DictStore[str, MailMessage]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    item_type = MailMessage

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

    @_syncs
    async def update(self) -> None:
        """Update `self` asynchronously using `self._fetch()`."""
        idents: set[str] = set()

        async for message in self._fetch():  # type: ignore
            idents.add(message.ident)
            if message.ident in self._items:
                continue

            self._items[message.ident] = MailMessage(message)
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
        self, futures: Iterable[Awaitable[Iterable[Message]]]
    ) -> AsyncGenerator[Message]:
        unread = set()
        async for messages in asyncio.as_completed(futures):
            # This is async interation, we don't want a data race
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


class MailDraftStore(DictStore[int, MailMessage]):
    """An implementation of `Gio.ListModel` for storing drafts."""

    item_type = MailMessage

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

    @_syncs
    async def update(self) -> None:
        """Update `self` by loading the latest drafts."""
        idents: set[int] = set()

        previous = len(self._items)
        self._items.clear()

        for draft in (drafts := tuple(client.load_drafts())):
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


class _BroadcastStore(MailMessageStore):
    async def _fetch(self) -> ...:
        async for message in self._process_messages(
            client.fetch_broadcasts(
                Address(contact.address),  # type: ignore
                exclude=settings.get_strv("deleted-messages"),
            )
            for contact in address_book
        ):
            yield message


class _InboxStore(MailMessageStore):
    async def _fetch(self) -> ...:
        known_notifiers = set()
        other_contacts = {Address(contact.address) for contact in address_book}  # type: ignore

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


class _OutboxStore(MailMessageStore):
    async def _fetch(self) -> ...:
        async for messages in asyncio.as_completed(
            (
                client.fetch_link_messages(user.address),
                client.fetch_broadcasts(user.address),
            )
        ):
            for message in await messages:
                message.new = False  # New outbox messages should be marked read

                yield message


profiles: defaultdict[Address, MailProfile] = defaultdict(MailProfile)
address_book = MailAddressBook()
contact_requests = MailContactRequests()

broadcasts = _BroadcastStore()
inbox = _InboxStore()
outbox = _OutboxStore()
drafts = MailDraftStore()

ProfileCategory = namedtuple("ProfileCategory", ("ident", "name"))
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
