# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from abc import abstractmethod
from collections import defaultdict
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Coroutine,
    Iterable,
    Iterator,
)
from dataclasses import fields
from datetime import UTC, date, datetime
from functools import partial
from gettext import ngettext
from itertools import chain
from shutil import rmtree
from typing import Any, Self, cast, override

import keyring
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from openemail import Notifier, create_task, secret_service, settings

from .core import client, model
from .core.client import WriteError, user
from .core.crypto import KeyPair
from .core.model import Address
from .dict_store import DictStore

MAX_PROFILE_IMAGE_DIMENSIONS = 800
ADDRESS_SPLIT_PATTERN = ",|;| "


def _ident(message: model.Message) -> str:
    return f"{message.author.host_part} {message.ident}"


class ProfileField(GObject.Object):
    """A profile field."""

    ident = GObject.Property(type=str)
    name = GObject.Property(type=str)

    def __init__(self, ident: str, name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.ident = ident
        self.name = name


class Category(GObject.Object, Gio.ListModel):  # pyright: ignore[reportIncompatibleMethodOverride]
    """A profile category."""

    ident = GObject.Property(type=str)
    name = GObject.Property(type=str)

    def __init__(
        self,
        ident: str,
        name: str,
        fields: dict[str, str],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.ident = ident
        self.name = name
        self._fields = tuple(ProfileField(K, V) for K, V in fields.items())

    def __iter__(self) -> Iterator[ProfileField]:
        return super().__iter__()  # pyright: ignore[reportReturnType]

    def do_get_item(self, position: int) -> ProfileField:
        """Get the item at `position`."""
        return self._fields[position]

    def do_get_item_type(self) -> type[ProfileField]:
        """Get the type of the items in `self`."""
        return ProfileField

    def do_get_n_items(self) -> int:
        """Get the number of items in `self`."""
        return len(self._fields)


class Profile(GObject.Object):
    """A GObject representation of a user profile."""

    __gtype_name__ = "Profile"

    updating = GObject.Property(type=bool, default=False)

    contact_request = GObject.Property(type=bool, default=False)
    has_name = GObject.Property(type=bool, default=False)
    has_image = GObject.Property(type=bool, default=False)

    categories = (
        Category(
            "general",
            _("General"),
            {
                "status": _("Status"),
                "about": _("About"),
            },
        ),
        Category(
            "personal",
            _("Personal"),
            {
                "gender": _("Gender"),
                "relationship-status": _("Relationship Status"),
                "birthday": _("Birthday"),
                "education": _("Education"),
                "languages": _("Languages"),
                "places-lived": _("Places Lived"),
                "notes": _("Notes"),
            },
        ),
        Category(
            "work",
            _("Work"),
            {
                "work": _("Work"),
                "organization": _("Organization"),
                "department": _("Department"),
                "job-title": _("Job Title"),
            },
        ),
        Category(
            "interests",
            _("Interests"),
            {
                "interests": _("Interests"),
                "books": _("Books"),
                "movies": _("Movies"),
                "music": _("Music"),
                "sports": _("Sports"),
            },
        ),
        Category(
            "contacts",
            _("Contact"),
            {
                "website": _("Website"),
                "location": _("Location"),
                "mailing-address": _("Mailing Address"),
                "phone": _("Phone"),
                "streams": _("Topics"),
            },
        ),
        Category(
            "configuration",
            _("Options"),
            {
                "public-access": _("People Can Reach Me"),
                "public-links": _("Public Contacts"),
                "last-seen-public": _("Share Presence"),
                "address-expansion": _("Address Expansion"),
            },
        ),
    )

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

        create_task(broadcasts.update())
        create_task(
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
        self.name = self.name or address

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
    default_factory = Profile.of

    async def update_profiles(self, *, trust_images: bool = True) -> None:
        """Update the profiles of contacts in the user's address book.

        If `trust_images` is set to `False`, profile images will not be loaded.
        """
        for address in (Address(contact.address) for contact in self):
            create_task(self._update_profile(address))
            if trust_images:
                create_task(self._update_profile_image(address))

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

    async def new(self, address: Address, *, receive_broadcasts: bool = True) -> None:
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

    async def delete(self, address: Address) -> None:
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

    async def _update(self) -> None:
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

    async def _update(self) -> None:
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


class Attachment(GObject.Object):
    """An file attached to a Mail/HTTPS message."""

    __gtype_name__ = "Attachment"

    name = GObject.Property(type=str)
    type = GObject.Property(type=str)
    size = GObject.Property(type=str)
    modified = GObject.Property(type=str)

    icon = GObject.Property(
        type=Gio.Icon,
        default=Gio.ThemedIcon.new("application-x-generic"),
    )

    can_remove = GObject.Property(type=bool, default=False)

    @abstractmethod
    def open(self) -> None:
        """Open `self` for viewing or saving."""

    @staticmethod
    def _get_window(parent: Gtk.Widget | None) -> Gtk.Window | None:
        return (
            parent.props.root
            if parent and isinstance(parent.props.root, Gtk.Window)
            else None
        )


class OutgoingAttachment(Attachment):
    """An attachment that has not yet been sent."""

    gfile = GObject.Property(type=Gio.File)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(can_remove=True, **kwargs)

    @override
    def open(self) -> None:
        """Open `self` for viewing."""
        if not self.gfile:
            return

        Gio.AppInfo.launch_default_for_uri(self.gfile.get_uri())

    @classmethod
    async def from_file(cls, gfile: Gio.File) -> Self:
        """Create an outgoing attachment from `gfile`.

        Raises ValueError if `gfile` doesn't have all required attributes.
        """
        try:
            info = await cast(
                "Awaitable[Gio.FileInfo]",
                gfile.query_info_async(
                    ",".join(
                        (
                            Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME,
                            Gio.FILE_ATTRIBUTE_TIME_MODIFIED,
                            Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE,
                            Gio.FILE_ATTRIBUTE_STANDARD_ICON,
                            Gio.FILE_ATTRIBUTE_STANDARD_SIZE,
                        )
                    ),
                    Gio.FileQueryInfoFlags.NONE,
                    GLib.PRIORITY_DEFAULT,
                ),
            )
        except GLib.Error as error:
            msg = "Could not create attachment: File missing required attributes"
            raise ValueError(msg) from error

        return cls(
            gfile=gfile,
            name=info.get_display_name(),
            type=Gio.content_type_get_mime_type(content_type)
            if (content_type := info.get_content_type())
            else None,
            size=GLib.format_size_for_display(info.get_size()),
            modified=datetime.format_iso8601()
            if (datetime := info.get_modification_date_time())
            else None,
            icon=info.get_icon(),
        )

    @classmethod
    async def choose(cls, parent: Gtk.Widget | None = None) -> AsyncGenerator[Self]:
        """Prompt the user to choose a attachments using the file picker."""
        try:
            gfiles = await cast(
                "Awaitable[Gio.ListModel]",
                Gtk.FileDialog().open_multiple(cls._get_window(parent)),
            )
        except GLib.Error:
            return

        for gfile in gfiles:
            if not isinstance(gfile, Gio.File):
                return

            try:
                yield await cls.from_file(gfile)
            except ValueError:
                continue


class IncomingAttachment(Attachment):
    """An attachment received by the user."""

    _parts: list[model.Message]

    def __init__(self, name: str, parts: list[model.Message], **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.name, self._parts = name, parts

        if not (parts and (props := parts[0].file)):
            return

        self.modified = props.modified
        self.type = props.type
        self.size = GLib.format_size_for_display(props.size)

        if not (content_type := Gio.content_type_from_mime_type(props.type)):
            return

        self.icon = Gio.content_type_get_icon(content_type)

    @override
    def open(self, parent: Gtk.Widget | None = None) -> None:
        """Download and reconstruct `self` from its parts, then open for saving."""
        create_task(self._save(parent))

    async def _save(self, parent: Gtk.Widget | None) -> None:
        msg = _("Failed to download attachment")

        try:
            gfile = await cast(
                "Awaitable[Gio.File]",
                Gtk.FileDialog(
                    initial_name=self.name,
                    initial_folder=Gio.File.new_for_path(downloads)
                    if (
                        downloads := GLib.get_user_special_dir(
                            GLib.UserDirectory.DIRECTORY_DOWNLOAD
                        )
                    )
                    else None,
                ).save(self._get_window(parent)),
            )
        except GLib.Error:
            return

        if not (data := await client.download_attachment(self._parts)):
            Notifier.send(msg)
            return

        try:
            stream = gfile.replace(
                etag=None,
                make_backup=False,
                flags=Gio.FileCreateFlags.REPLACE_DESTINATION,
            )
            await cast(
                "Awaitable[int]",
                stream.write_bytes_async(GLib.Bytes.new(data), GLib.PRIORITY_DEFAULT),
            )
            await cast(
                "Awaitable[bool]",
                stream.close_async(GLib.PRIORITY_DEFAULT),
            )

        except GLib.Error:
            Notifier.send(msg)
            return

        if self.modified and (
            datetime := GLib.DateTime.new_from_iso8601(self.modified)
        ):
            info = Gio.FileInfo()
            info.set_modification_date_time(datetime)
            gfile.set_attributes_from_info(
                info, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS
            )

        Gio.AppInfo.launch_default_for_uri(gfile.get_uri())


class Message(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "Message"

    date = GObject.Property(type=str)
    datetime = GObject.Property(type=str)
    unix = GObject.Property(type=int)

    subject = GObject.Property(type=str)
    body = GObject.Property(type=str)
    unread = GObject.Property(type=bool, default=False)

    subject_id = GObject.Property(type=str)
    draft_id = GObject.Property(type=str)
    broadcast = GObject.Property(type=bool, default=False)

    can_reply = GObject.Property(type=bool, default=False)
    outgoing = GObject.Property(type=bool, default=False)
    incoming = GObject.Property(type=bool, default=True)
    can_trash = GObject.Property(type=bool, default=False)

    original_author = GObject.Property(type=str)
    different_author = GObject.Property(type=bool, default=False)
    readers = GObject.Property(type=str)
    reader_addresses = GObject.Property(type=str)

    attachments = GObject.Property(type=Gio.ListStore)

    name = GObject.Property(type=str)
    icon_name = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)
    show_initials = GObject.Property(type=bool, default=False)
    profile = GObject.Property(type=Profile)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    _message: model.Message | None = None

    @property
    def author(self) -> Address | None:
        """The author of `self`."""
        return self._message.author if self._message else None

    @GObject.Property(type=bool, default=False)
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if not self._message:
            return False

        return any(
            msg.rsplit(maxsplit=1)[0] == _ident(self._message)
            for msg in settings.get_strv("trashed-messages")
        )

    def __init__(self, message: model.Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attachments = Gio.ListStore.new(Attachment)
        self.set_from_message(message)

    def set_from_message(self, message: model.Message | None) -> None:
        """Set the properties of `self` from `message`."""
        self._message = message

        if not message:
            return

        local_date = message.date.astimezone(
            datetime.now(UTC).astimezone().tzinfo,
        )

        self.date = local_date.strftime("%x")
        # Localized date format, time in H:M
        self.datetime = _("{} at {}").format(self.date, local_date.strftime("%H:%M"))
        self.unix = int(local_date.timestamp())

        self.subject = message.subject
        self.body = message.body or ""
        self.unread = message.new

        self.outgoing = message.author == user.address
        self.incoming = not self.outgoing

        self._update_trashed_state()

        self.original_author = f"{_('Original Author:')} {message.original_author}"
        self.different_author = message.author != message.original_author

        readers = tuple(r for r in message.readers if r != user.address)
        if message.is_broadcast:
            self.readers = _("Public Message")
        else:
            # Others will be appended to this string in the format: ", reader1, reader2"
            self.readers = _("Readers: Me")
            for reader in readers:
                self.readers += f", {Profile.of(reader).name or reader}"

        self.reader_addresses = ", ".join(
            map(str, readers if self.outgoing else (*readers, message.author))
        )

        self.attachments.remove_all()
        for name, parts in message.attachments.items():
            self.attachments.append(IncomingAttachment(name, parts))

        match message:
            case client.IncomingMessage():
                self.subject_id = message.subject_id
            case client.DraftMessage():
                self.draft_id = message.ident
            case _:
                pass

        for binding in (self._name_binding, self._image_binding):
            if binding:
                binding.unbind()

        self._name_binding = self._image_binding = None
        self.profile = self.profile_image = None
        self.show_initials = False

        if not (message.readers or message.is_broadcast):
            self.name = _("No Readers")
            self.icon_name = "public-access-symbolic"
            return

        if self.outgoing and message.is_broadcast:
            self.name = _("Public Message")
            self.icon_name = "broadcasts-symbolic"
            return

        if self.outgoing and (len(readers) > 1):
            self.name = ngettext(
                "{} Reader",
                "{} Readers",
                len(readers),
            ).format(len(readers))
            self.icon_name = "contacts-symbolic"
            return

        self.profile = Profile.of(
            readers[0] if (self.outgoing and readers) else message.author
        )

        self._name_binding = self.profile.bind_property(
            "name", self, "name", GObject.BindingFlags.SYNC_CREATE
        )

        self.show_initials = True
        self._image_binding = self.profile.bind_property(
            "image", self, "profile-image", GObject.BindingFlags.SYNC_CREATE
        )

    def trash(self) -> None:
        """Move `self` to the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            (
                *settings.get_strv("trashed-messages"),
                f"{_ident(self._message)} {datetime.now(UTC).date().isoformat()}",
            ),
        )

        self._update_trashed_state()

    def restore(self) -> None:
        """Restore `self` from the trash."""
        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(
                msg
                for msg in settings.get_strv("trashed-messages")
                if msg.rsplit(maxsplit=1)[0] != _ident(self._message)
            ),
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

        # TODO: Better UX, cancellation?
        if isinstance(self._message, client.OutgoingMessage) and self._message.sending:
            Notifier.send(_("Cannot discard message while sending"))
            return

        outbox.remove(_ident(self._message))

        failed = False
        for msg in (self._message, *self._message.children):
            try:
                await client.delete_message(msg.ident)
            except WriteError:  # noqa: PERF203
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
        self.can_trash = not (self.outgoing or self.trashed)
        self.can_reply = not self.trashed
        self.notify("trashed")


class MessageStore(DictStore[str, Message]):
    """An implementation of `Gio.ListModel` for storing Mail/HTTPS messages."""

    item_type = Message
    key_for = _ident
    default_factory = Message

    async def _update(self) -> None:
        idents = set[str]()

        async for message in self._fetch():
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
    def _fetch(self) -> AsyncGenerator[model.Message]: ...

    async def _process_messages(
        self, futures: AsyncIterable[Iterable[model.Message]]
    ) -> AsyncGenerator[model.Message]:
        unread = set[str]()
        async for messages in futures:
            current_unread = settings.get_strv("unread-messages")

            for message in messages:
                if message.new:
                    unread.add(_ident(message))

                elif _ident(message) in current_unread:
                    message.new = True

                yield message

        settings.set_strv(
            "unread-messages",
            tuple(set(settings.get_strv("unread-messages")) | unread),
        )


class _BroadcastStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        deleted = settings.get_strv("deleted-messages")
        async for message in self._process_messages(
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
            yield message


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
        async for message in self._process_messages(
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
            yield message


class _OutboxStore(MessageStore):
    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for message in await client.fetch_outbox():
            message.new = False  # New outbox messages should be marked read
            yield message


class _DraftStore(MessageStore):
    """An implementation of `Gio.ListModel` for storing drafts."""

    def save(
        self,
        ident: str | None = None,
        readers: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        reply: str | None = None,
    ) -> None:
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

    def delete(self, ident: str) -> None:
        """Delete a draft saved using `save()`."""
        client.delete_draft(ident)
        self.remove(ident)

    def delete_all(self) -> None:
        """Delete all drafts saved using `save()`."""
        client.delete_all_drafts()
        self.clear()

    async def _fetch(self) -> AsyncGenerator[model.Message]:
        for message in tuple(client.load_drafts()):
            yield message


_profiles: defaultdict[Address, Profile] = defaultdict(Profile)
address_book = _AddressBook()
contact_requests = _ContactRequests()
user_profile = Profile()

broadcasts = _BroadcastStore()
inbox = _InboxStore()
outbox = _OutboxStore()
drafts = _DraftStore()


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

    create_task(auth(), done)


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

    create_task(auth(), done)


async def sync(*, periodic: bool = False) -> None:
    """Populate the app's content by fetching the user's data."""
    Notifier().syncing = True

    if periodic and (interval := settings.get_uint("sync-interval")):
        GLib.timeout_add_seconds(interval, create_task, sync(periodic=True))

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
        contact_requests.update(),
        broadcasts.update(),
        inbox.update(),
        outbox.update(),
        drafts.update(),
    }

    def done(task: Coroutine[Any, Any, Any]) -> None:
        tasks.discard(task)
        if not tasks:
            Notifier().syncing = False

    for task in tasks:
        create_task(task, lambda _, t=task: done(t))

    settings.connect(
        "changed::contact-requests",
        lambda *_: create_task(contact_requests.update()),
    )


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
        user.signing_keys = KeyPair(
            user.signing_keys.private,
            profile.signing_key,
        )

        if profile.encryption_key:
            user.encryption_keys = KeyPair(
                user.encryption_keys.private,
                profile.encryption_key,
            )

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
    attachments: Iterable[OutgoingAttachment] = (),
) -> None:
    """Send a message to `readers`.

    If `readers` is empty, send a broadcast.

    `reply` is an optional `Subject-ID` of a thread that the message should be part of.

    `attachments` is a dictionary of `Gio.File`s and filenames.
    """
    Notifier().sending = True

    files = dict[model.AttachmentProperties, bytes]()
    for attachment in attachments:
        try:
            _success, data, _etag = await cast(
                "Awaitable[tuple[bool, bytes, str]]",
                attachment.gfile.load_contents_async(),
            )
        except GLib.Error as error:
            Notifier.send(_("Failed to send message"))
            Notifier().sending = False
            raise WriteError from error

        files[
            model.AttachmentProperties(
                name=attachment.name,
                ident=model.generate_ident(client.user.address),
                type=attachment.type,
                modified=attachment.modified,
            )
        ] = data

    outbox.add(
        message := client.OutgoingMessage(
            readers=list(readers),
            subject=subject,
            body=body,
            subject_id=reply,
            files=files,
        )
    )

    try:
        await message.send()
    except WriteError:
        outbox.remove(message.ident)
        Notifier.send(_("Failed to send message"))
        Notifier().sending = False
        raise

    Notifier().sending = False


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
    settings.reset("empty-trash-interval")
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


if interval := settings.get_uint("empty-trash-interval"):
    deleted = set[str]()
    new_trashed = list[str]()

    today = datetime.now(UTC).date()
    for message in settings.get_strv("trashed-messages"):
        ident, timestamp = message.rsplit(maxsplit=1)

        try:
            trashed = date.fromisoformat(timestamp)
        except ValueError:
            continue

        if today.day - trashed.day >= interval:
            deleted.add(ident)
        else:
            new_trashed.append(message)

    settings.set_strv("trashed-messages", new_trashed)
    settings.set_strv(
        "deleted-messages",
        tuple(set(settings.get_strv("deleted-messages")) | deleted),
    )
