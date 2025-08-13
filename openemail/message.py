# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from abc import abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Iterable
from datetime import UTC, datetime
from gettext import ngettext
from typing import Any, Self, cast, override

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from . import core
from .asyncio import create_task
from .core import client, model
from .core.client import WriteError, user
from .core.model import Address
from .notifier import Notifier
from .profile import Profile


def get_ident(message: model.Message) -> str:
    """Get a globally unique identifier for `message`."""
    return f"{message.author.host_part} {message.ident}"


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
    def open(self):
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

    def __init__(self, **kwargs: Any):
        super().__init__(can_remove=True, **kwargs)

    @override
    def open(self):
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

    def __init__(self, name: str, parts: list[model.Message], **kwargs: Any):
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
    def open(self, parent: Gtk.Widget | None = None):
        """Download and reconstruct `self` from its parts, then open for saving."""
        create_task(self._save(parent))

    async def _save(self, parent: Gtk.Widget | None):
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
        from .store import settings

        if not self._message:
            return False

        return any(
            msg.rsplit(maxsplit=1)[0] == get_ident(self._message)
            for msg in settings.get_strv("trashed-messages")
        )

    def __init__(self, message: model.Message | None = None, **kwargs: Any):
        super().__init__(**kwargs)

        self.attachments = Gio.ListStore.new(Attachment)
        self.set_from_message(message)

    def set_from_message(self, message: model.Message | None):
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

    def trash(self):
        """Move `self` to the trash."""
        from .store import settings

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

    def restore(self):
        """Restore `self` from the trash."""
        from .store import settings

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

    def delete(self):
        """Remove `self` from the trash."""
        from .store import broadcasts, inbox, settings

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

    async def discard(self):
        """Discard `self` and its children."""
        from .store import outbox

        if not self._message:
            return

        # TODO: Better UX, cancellation?
        if isinstance(self._message, model.OutgoingMessage) and self._message.sending:
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

    def mark_read(self):
        """Mark a message as read.

        Does nothing if the message is not unread.
        """
        from .store import settings

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

    def _update_trashed_state(self):
        self.can_trash = not (self.outgoing or self.trashed)
        self.can_reply = not self.trashed
        self.notify("trashed")


async def send(
    readers: Iterable[Address],
    subject: str,
    body: str,
    reply: str | None = None,
    attachments: Iterable[OutgoingAttachment] = (),
):
    """Send a message to `readers`.

    If `readers` is empty, send a broadcast.

    `reply` is an optional `Subject-ID` of a thread that the message should be part of.

    `attachments` is a dictionary of `Gio.File`s and filenames.
    """
    from .store import outbox

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
                ident=model.generate_ident(core.user.address),
                type=attachment.type,
                modified=attachment.modified,
            )
        ] = data

    outbox.add(
        message := model.OutgoingMessage(
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
