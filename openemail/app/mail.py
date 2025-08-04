# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from abc import abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Iterable, Iterator
from datetime import UTC, datetime
from gettext import ngettext
from typing import TYPE_CHECKING, Any, Self, cast, override

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from openemail import app
from openemail.core import client, model
from openemail.core.client import WriteError, user
from openemail.core.crypto import KeyPair
from openemail.core.model import Address

from . import Notifier

if TYPE_CHECKING:
    from openemail.widgets.compose_sheet import ComposeSheet


compose_sheet: "ComposeSheet"

MAX_PROFILE_IMAGE_DIMENSIONS = 800


def get_ident(message: model.Message) -> str:
    """Get a globally unique identifier for `message`."""
    return f"{message.author.host_part} {message.ident}"


class ProfileField(GObject.Object):
    """A field for information on a user."""

    ident = GObject.Property(type=str)
    name = GObject.Property(type=str)

    def __init__(self, ident: str, name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.ident = ident
        self.name = name


class ProfileCategory(GObject.Object, Gio.ListModel):  # pyright: ignore[reportIncompatibleMethodOverride]
    """A category of profile fields."""

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
        ProfileCategory(
            "general",
            _("General"),
            {
                "status": _("Status"),
                "about": _("About"),
            },
        ),
        ProfileCategory(
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
        ProfileCategory(
            "work",
            _("Work"),
            {
                "work": _("Work"),
                "organization": _("Organization"),
                "department": _("Department"),
                "job-title": _("Job Title"),
            },
        ),
        ProfileCategory(
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
        ProfileCategory(
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
        ProfileCategory(
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
        from .store import broadcasts  # noqa: PLC0415

        if self._broadcasts == receive_broadcasts or (not self._profile):
            return

        self._broadcasts = receive_broadcasts

        app.create_task(broadcasts.update())
        app.create_task(
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
        from .store import profiles  # noqa: PLC0415

        (profile := profiles[address]).address = str(address)
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
        app.create_task(self._save(parent))

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
        from .store import settings  # noqa: PLC0415

        if not self._message:
            return False

        return any(
            msg.rsplit(maxsplit=1)[0] == get_ident(self._message)
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
        from .store import settings  # noqa: PLC0415

        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            (
                *settings.get_strv("trashed-messages"),
                f"{get_ident(self._message)} {datetime.now(UTC).date().isoformat()}",
            ),
        )

        self._update_trashed_state()

    def restore(self) -> None:
        """Restore `self` from the trash."""
        from .store import settings  # noqa: PLC0415

        if not self._message:
            return

        settings.set_strv(
            "trashed-messages",
            tuple(
                msg
                for msg in settings.get_strv("trashed-messages")
                if msg.rsplit(maxsplit=1)[0] != get_ident(self._message)
            ),
        )

        self._update_trashed_state()

    def delete(self) -> None:
        """Remove `self` from the trash."""
        from .store import broadcasts, inbox, settings  # noqa: PLC0415

        if not self._message:
            return

        settings.set_strv(
            "deleted-messages",
            tuple(
                set(settings.get_strv("deleted-messages")) | {get_ident(self._message)}
            ),
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
            get_ident(self._message)
        )
        self.restore()
        self.set_from_message(None)

    async def discard(self) -> None:
        """Discard `self` and its children."""
        from .store import outbox  # noqa: PLC0415

        if not self._message:
            return

        # TODO: Better UX, cancellation?
        if isinstance(self._message, client.OutgoingMessage) and self._message.sending:
            Notifier.send(_("Cannot discard message while sending"))
            return

        outbox.remove(get_ident(self._message))

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
        from .store import settings  # noqa: PLC0415

        if not self.unread:
            return

        self.unread = False

        if not self._message:
            return

        self._message.new = False
        settings.set_strv(
            "unread-messages",
            tuple(
                set(settings.get_strv("unread-messages")) - {get_ident(self._message)}
            ),
        )

    def _update_trashed_state(self) -> None:
        self.can_trash = not (self.outgoing or self.trashed)
        self.can_reply = not self.trashed
        self.notify("trashed")


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
    from .store import user_profile  # noqa: PLC0415

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
    from .store import outbox  # noqa: PLC0415

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
