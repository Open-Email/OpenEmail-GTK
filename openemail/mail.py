# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import asyncio
import operator
from abc import abstractmethod
from collections import defaultdict
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Iterable
from dataclasses import fields
from datetime import datetime, timezone
from itertools import chain
from shutil import rmtree
from typing import Any, ClassVar, NamedTuple, cast

import keyring
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from openemail import Notifier, run_task, secret_service, settings

from .core import client, model
from .core.client import WriteError, user
from .core.crypto import KeyPair  # noqa: F401
from .core.model import Address
from .dict_store import DictStore

MAX_PROFILE_IMAGE_DIMENSIONS = 800


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

        Notifier.send(_("Authentication failed"))

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

        Notifier.send(_("Registration failed, try another address"))

        if on_failure:
            on_failure()

    run_task(auth(), done)


async def sync(periodic: bool = False) -> None:
    """Populate the app's content by fetching the user's data."""
    notifier = Notifier.get_default()
    notifier.emit("sync-started")

    if periodic and (interval := settings.get_uint("sync-interval")):
        GLib.timeout_add_seconds(interval or 60, sync, True)

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
        update_user_profile(),
        address_book.update_profiles(),
        broadcasts.update(),
        inbox.update(),
        outbox.update(),
        drafts.update(),
    }

    def done(task: Coroutine[Any, Any, Any]) -> None:
        tasks.discard(task)
        if not tasks:
            notifier.emit("sync-finished")

    for task in tasks:
        run_task(task, lambda _, t=task: done(t))


async def update_profile(values: dict[str, str]) -> None:
    """Update the user's public profile with `values`."""
    try:
        await client.update_profile(values)
    except WriteError:
        Notifier.send(_("Failed to update profile"))
        raise

    await update_user_profile()


async def update_profile_image(pixbuf: GdkPixbuf.Pixbuf) -> None:
    """Upload `pixbuf` to be used as the user's profile image."""
    if (width := pixbuf.props.width) > (height := pixbuf.props.height):
        if width > MAX_PROFILE_IMAGE_DIMENSIONS:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=int(width * (MAX_PROFILE_IMAGE_DIMENSIONS / height)),
                    dest_height=MAX_PROFILE_IMAGE_DIMENSIONS,
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
        if height > MAX_PROFILE_IMAGE_DIMENSIONS:
            pixbuf = (
                pixbuf.scale_simple(
                    dest_width=MAX_PROFILE_IMAGE_DIMENSIONS,
                    dest_height=int(height * (MAX_PROFILE_IMAGE_DIMENSIONS / width)),
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
        Notifier.send(_("Failed to update profile image"))
        raise WriteError from error

    if not success:
        Notifier.send(_("Failed to update profile image"))
        raise WriteError

    try:
        await client.update_profile_image(data)
    except WriteError:
        Notifier.send(_("Failed to update profile image"))
        raise

    await update_user_profile()


async def update_user_profile() -> None:
    """Update the profile of the user by fetching new data remotely."""
    user_profile.updating = True
    user_profile.set_from_profile(profile := await client.fetch_profile(user.address))

    if profile:
        user.signing_keys.public = profile.signing_key

        if profile.encryption_key:
            user.encryption_keys.public = profile.encryption_key

    try:
        user_profile.image = Gdk.Texture.new_from_bytes(
            GLib.Bytes.new(await client.fetch_profile_image(user.address))
        )
    except GLib.Error:
        user_profile.image = None

    Profile.of(user.address).image = user_profile.image
    Profile.of(user.address).set_from_profile(profile)
    user_profile.updating = False


async def delete_profile_image() -> None:
    """Delete the user's profile image."""
    try:
        await client.delete_profile_image()
    except WriteError:
        Notifier.send(_("Failed to delete profile image"))
        raise

    await update_user_profile()


async def send_message(
    readers: Iterable[Address],
    subject: str,
    body: str,
    reply: str | None = None,
    attachments: dict[Gio.File, str] | None = None,
) -> None:
    """Send `message` to `readers`.

    If `readers` is empty, send a broadcast.

    `reply` is an optional `Subject-ID` of a thread that the message should be part of.

    `attachments` is a dictionary of `Gio.File`s and filenames.
    """
    Notifier.send(_("Sending message…"))

    files = {}
    attachments = attachments or {}
    for gfile, name in attachments.items():
        try:
            _success, data, _etag = await cast(
                "Awaitable[tuple[bool, bytes, str]]", gfile.load_contents_async()
            )
        except GLib.Error as error:
            raise WriteError from error

        files[name] = data

    try:
        await client.send_message(readers, subject, body, reply, attachments=files)
    except WriteError:
        Notifier.send(_("Failed to send message"))
        raise

    await outbox.update()


def empty_trash() -> None:
    """Empty the user's trash."""
    for message in tuple(m for m in chain(inbox, broadcasts) if m.trashed):
        message.delete()


def log_out() -> None:
    """Remove the user's local account."""
    for profile in _profiles.values():
        profile.set_from_profile(None)

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

    for field in fields(model.User):
        delattr(user, field.name)


async def delete_account() -> None:
    """Permanently delete the user's account."""
    try:
        await client.delete_account()
    except WriteError:
        Notifier.send(_("Failed to delete account"))
        return

    log_out()


class Profile(GObject.Object):
    """A GObject representation of a user profile."""

    __gtype_name__ = "Profile"

    updating = GObject.Property(type=bool, default=False)

    contact_request = GObject.Property(type=bool, default=False)
    has_name = GObject.Property(type=bool, default=False)
    has_image = GObject.Property(type=bool, default=False)

    class Category(NamedTuple):
        """A category of profile fields."""

        ident: str
        name: str

    categories: ClassVar[dict[Category, dict[str, str]]] = {
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
    _image: Gdk.Paintable | None = None

    def set_from_profile(self, profile: model.Profile | None) -> None:
        """Set the properties of `self` from `profile`."""
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
        if self._broadcasts == receive_broadcasts or (not self._profile):
            return

        self._broadcasts = receive_broadcasts

        run_task(broadcasts.update())
        run_task(
            client.new_contact(
                self._profile.address,
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

    @GObject.Property(type=Gdk.Paintable)
    def image(self) -> Gdk.Paintable | None:
        """Get the profile owner's profile image."""
        return self._image

    @image.setter
    def image(self, image: Gdk.Paintable | None) -> None:
        self._image = image
        self.has_image = bool(image)

    @staticmethod
    def of(address: Address) -> "Profile":
        """Get the profile associated with `address`."""
        (profile := _profiles[address]).address = str(address)
        return profile

    def value_of(self, ident: str) -> Any:
        """Get the value of the field identified by `ident` in `self`."""
        try:
            return getattr(self._profile, ident.replace("-", "_"))
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
        Profile.of(address).set_from_profile(await client.fetch_profile(address))

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


class _AddressBook(ProfileStore):
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
        except WriteError:
            self.remove(address)
            run_task(broadcasts.update())
            run_task(inbox.update())

            Notifier.send(_("Failed to add contact"))
            raise

    async def delete(self, address: Address) -> None:
        """Delete `address` from the user's address book."""
        self.remove(address)
        run_task(broadcasts.update())
        run_task(inbox.update())

        try:
            await client.delete_contact(address)
        except WriteError:
            self.add(address)
            run_task(broadcasts.update())
            run_task(inbox.update())

            Notifier.send(_("Failed to remove contact"))
            raise

    async def _update(self) -> None:
        """Update `self` from remote data asynchronously."""
        contacts: set[Address] = set()

        for contact, receives_broadcasts in await client.fetch_contacts():
            contacts.add(contact)
            self.add(contact, receives_broadcasts=receives_broadcasts)

        for address in self._items.copy():
            if address not in contacts:
                self.remove(address)


class _ContactRequests(ProfileStore):
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

    _parts: list[model.Message]

    def __init__(self, name: str, parts: list[model.Message], **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.name, self._parts = name, parts

    async def download(self) -> bytes | None:
        """Download and reconstruct `self` from its parts."""
        if not (data := await client.download_attachment(self._parts)):
            Notifier.send(_("Failed to download attachment"))
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
    def author(self) -> Address | None:
        """The author of `self`."""
        return self._message.author if self._message else None

    @property
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if not self._message:
            return False

        return _ident(self._message) in settings.get_strv("trashed-messages")

    def __init__(self, message: model.Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attachments = Gio.ListStore.new(Attachment)
        self.set_from_message(message)

    def set_from_message(self, message: model.Message | None) -> None:
        """Set the properties of `self` from `message`."""
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
            self.date,
            message.date.astimezone(
                datetime.now(timezone.utc).tzinfo,
            ).strftime("%H:%M"),
        )

        self.subject = message.subject
        self.body = message.body or ""
        self.unread = message.new

        self.author_is_self = message.author == user.address

        self._update_trashed_state()

        self.original_author = f"{_('Original Author:')} {message.original_author}"
        self.different_author = message.author != message.original_author

        if message.is_broadcast:
            self.readers = _("Broadcast")
        else:
            self.readers = f"{_('Readers:')} {user_profile.name}"
            for reader in message.readers:
                if reader == user.address:
                    continue

                self.readers += f", {Profile.of(reader).name or reader}"

        self.reader_addresses = ", ".join(
            str(reader)
            for reader in list(dict.fromkeys((*message.readers, message.author)))
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

    def trash(self) -> None:
        """Move `self` to the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(set(settings.get_strv("trashed-messages")) | {_ident(self._message)}),
        )

        self._update_trashed_state()

    def restore(self) -> None:
        """Restore `self` from the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(set(settings.get_strv("trashed-messages")) - {_ident(self._message)}),
        )

        self._update_trashed_state()

    def delete(self) -> None:
        """Remove `self` from the trash."""
        if not self._message:
            return

        settings.set_strv(
            "deleted-messages",
            tuple(set(settings.get_strv("deleted-messages")) | {_ident(self._message)}),
        )

        envelopes_dir = (
            client.data_dir
            / "envelopes"
            / self._message.author.host_part
            / self._message.author.local_part
        )
        messages_dir = (
            client.data_dir
            / "messages"
            / self._message.author.host_part
            / self._message.author.local_part
        )

        if self._message.is_broadcast:
            envelopes_dir /= "broadcasts"
            messages_dir /= "broadcasts"

        for child in (self._message, *self._message.children):
            (envelopes_dir / f"{child.ident}.json").unlink(missing_ok=True)
            (messages_dir / child.ident).unlink(missing_ok=True)

        (broadcasts if self._message.is_broadcast else inbox).remove(
            _ident(self._message)
        )
        self.restore()
        self.set_from_message(None)

    async def discard(self) -> None:
        """Discard `self` and its children."""
        if not self._message:
            return

        outbox.remove(_ident(self._message))

        failed = False
        for msg in (self._message, *self._message.children):
            try:
                await client.delete_message(msg.ident)
            except WriteError:
                if not failed:
                    Notifier.send(_("Failed to discard message"))

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

        if not self._message:
            return

        self._message.new = False
        settings.set_strv(
            "unread-messages",
            tuple(set(settings.get_strv("unread-messages")) - {_ident(self._message)}),
        )

    def _update_trashed_state(self) -> None:
        self.can_trash = not (self.author_is_self or self.trashed)
        self.can_restore = self.trashed
        self.can_reply = not self.can_restore

    def _compare(self, other: object, func: Callable[[Any, Any], bool]) -> bool:
        if not (self._message and isinstance(other, Message) and other._message):  # noqa: SLF001 https://github.com/astral-sh/ruff/issues/3933
            return func(True, True)

        return func(self.datetime, other.datetime)

    def __eq__(self, other: object) -> bool:
        return self._compare(other, operator.eq)

    def __ne__(self, other: object) -> bool:
        return self._compare(other, operator.ne)

    def __lt__(self, other: object) -> bool:
        return self._compare(other, operator.lt)

    def __gt__(self, other: object) -> bool:
        return self._compare(other, operator.gt)

    def __le__(self, other: object) -> bool:
        return self._compare(other, operator.le)

    def __ge__(self, other: object) -> bool:
        return self._compare(other, operator.ge)


class MessageStore(DictStore[str, Message]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    item_type = Message

    async def _update(self) -> None:
        """Update `self` asynchronously using `self._fetch()`."""
        idents: set[str] = set()

        async for message in self._fetch():  # type: ignore
            ident = _ident(message)

            idents.add(ident)
            if ident in self._items:
                continue

            self._items[ident] = Message(message)
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
                    unread.add(_ident(message))

                elif _ident(message) in current_unread:
                    message.new = True

                yield message

        settings.set_strv(
            "unread-messages",
            tuple(set(settings.get_strv("unread-messages")) | unread),
        )


class _DraftStore(DictStore[int, Message]):
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

        `draft_id` can be used to update a specific draft,
        by default, a new ID is generated.
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
                address := Address(contact.address),
                exclude=(
                    split[1]
                    for ident in settings.get_strv("deleted-messages")
                    if (split := ident.split(" "))[0] == address.host_part
                ),
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

            settings.set_strv("contact-requests", [*current, str(notifier)])

        deleted = settings.get_strv("deleted-messages")
        async for message in self._process_messages(
            (
                client.fetch_link_messages(
                    contact,
                    exclude=(
                        split[1]
                        for ident in deleted
                        if (split := ident.split(" "))[0] == contact.host_part
                    ),
                )
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
address_book = _AddressBook()
contact_requests = _ContactRequests()
user_profile = Profile()

broadcasts = _BroadcastStore()
inbox = _InboxStore()
outbox = _OutboxStore()
drafts = _DraftStore()


def _ident(message: model.Message) -> str:
    return f"{message.author.host_part} {message.ident}"


run_task(sync(periodic=True))
