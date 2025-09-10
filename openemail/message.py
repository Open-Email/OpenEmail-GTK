# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from abc import abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Iterable
from contextlib import suppress
from datetime import UTC, datetime
from gettext import ngettext
from pathlib import Path
from typing import Any, Self, cast, override

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from . import Notifier, Property, core, tasks
from .core import client, messages, model
from .core.model import Address, WriteError
from .profile import Profile


def get_ident(message: model.Message) -> str:
    """Get a globally unique identifier for `message`."""
    return f"{message.author.host_part} {message.ident}"


class Attachment(GObject.Object):
    """An file attached to a Mail/HTTPS message."""

    __gtype_name__ = "Attachment"

    name = Property(str)
    type = Property(str)
    size = Property(str)
    modified = Property(str)

    icon = Property(Gio.Icon, default=Gio.ThemedIcon.new("application-x-generic"))

    can_remove = Property(bool)

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

    __gtype_name__ = "OutgoingAttachment"

    file = Property(Gio.File)

    def __init__(self, **kwargs: Any):
        super().__init__(can_remove=True, **kwargs)

    @override
    def open(self):
        """Open `self` for viewing."""
        if not self.file:
            return

        Gio.AppInfo.launch_default_for_uri(self.file.get_uri())

    @classmethod
    async def from_file(cls, file: Gio.File) -> Self:
        """Create an outgoing attachment from `file`.

        Raises ValueError if `file` doesn't have all required attributes.
        """
        try:
            info = await cast(
                "Awaitable[Gio.FileInfo]",
                file.query_info_async(
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
            file=file,
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
            files = await cast(
                "Awaitable[Gio.ListModel]",
                Gtk.FileDialog().open_multiple(cls._get_window(parent)),
            )
        except GLib.Error:
            return

        for file in files:
            if not isinstance(file, Gio.File):
                return

            try:
                yield await cls.from_file(file)
            except ValueError:
                continue


class IncomingAttachment(Attachment):
    """An attachment received by the user."""

    __gtype_name__ = "IncomingAttachment"

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
        tasks.create(self._save(parent))

    async def _save(self, parent: Gtk.Widget | None):
        msg = _("Failed to download attachment")

        try:
            file = await cast(
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

        if not (data := await messages.download_attachment(self._parts)):
            Notifier.send(msg)
            return

        try:
            stream = file.replace(
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
            file.set_attributes_from_info(
                info, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS
            )

        Gio.AppInfo.launch_default_for_uri(file.get_uri())


class Message(GObject.Object):
    """A Mail/HTTPS message."""

    __gtype_name__ = "Message"

    draft_id = Property(str)
    author = Property(str)
    original_author = Property(str)
    date = Property(int)
    subject = Property(str)
    subject_id = Property(str)
    readers = Property(str)
    attachments = Property(Gio.ListStore)
    body = Property(str)
    new = Property(bool)
    is_broadcast = Property(bool)

    display_date = Property(str)
    display_datetime = Property(str)
    display_readers = Property(str)
    display_name = Property(str)
    profile = Property(Profile)
    profile_image = Property(Gdk.Paintable)
    icon_name = Property(str)
    show_initials = Property(bool)

    is_outgoing, is_incoming = Property(bool), Property(bool, default=True)
    different_author = Property(bool)
    can_reply = Property(bool)
    can_trash = Property(bool)
    can_discard = Property(bool)

    _bindings: tuple[GObject.Binding, ...] = ()
    _message: model.Message | None = None

    @Property(bool)
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        from .store import settings

        if self.can_discard or (not self._message):
            return False

        return any(
            msg.rsplit(maxsplit=1)[0] == get_ident(self._message)
            for msg in settings.get_strv("trashed-messages")
        )

    def __init__(self, message: model.Message | None = None, **kwargs: Any):
        super().__init__(**kwargs)

        self.attachments = Gio.ListStore.new(Attachment)
        self.set_from_message(message)

    def __hash__(self) -> int:
        return hash(self._message.ident) if self._message else super().__hash__()

    def __eq__(self, value: object, /) -> bool:
        if isinstance(value, Message) and self._message and value._message:
            return self._message.ident == value._message.ident
        return super().__eq__(value)

    def __ne__(self, value: object, /) -> bool:
        if isinstance(value, Message) and self._message and value._message:
            return self._message.ident != value._message.ident
        return super().__ne__(value)

    def set_from_message(self, msg: model.Message | None, /):
        """Set the properties of `self` from `message`."""
        self._message = msg

        if not msg:
            return

        local_date = msg.date.astimezone(datetime.now(UTC).astimezone().tzinfo)
        self.date = int(local_date.timestamp())
        self.display_date = local_date.strftime("%x")
        # Localized date format, time in H:M
        self.display_datetime = _("{} at {}").format(
            self.display_date, local_date.strftime("%H:%M")
        )

        self.subject = msg.subject
        self.body = msg.body or ""
        self.new = msg.new
        self.is_broadcast = msg.is_broadcast

        self.is_outgoing = msg.author == client.user.address
        self.is_incoming = not self.is_outgoing
        self._update_trashed_state()

        self.author = msg.author
        self.original_author = f"{_('Original Author:')} {msg.original_author}"
        self.different_author = msg.author != msg.original_author

        readers = tuple(r for r in msg.readers if r != client.user.address)
        if self.is_broadcast:
            self.display_readers = _("Public Message")
        else:
            # Others will be appended to this string in the format: ", reader1, reader2"
            self.display_readers = _("Readers: Me")
            for reader in readers:
                self.display_readers += f", {Profile.of(reader).name or reader}"

        self.readers = ", ".join(
            map(str, readers if self.is_outgoing else (*readers, msg.author))
        )

        self.attachments.remove_all()
        for name, parts in msg.attachments.items():
            self.attachments.append(IncomingAttachment(name, parts))

        match msg:
            case model.IncomingMessage() | model.OutgoingMessage():
                self.subject_id = msg.subject_id
            case model.DraftMessage():
                self.draft_id = msg.ident

        for binding in self._bindings:
            binding.unbind()

        self._bindings = ()

        self.profile = self.profile_image = None
        self.show_initials = False

        if not (msg.readers or msg.is_broadcast):
            self.display_name = _("No Readers")
            self.icon_name = "public-access-symbolic"
            return

        if self.is_outgoing and msg.is_broadcast:
            self.display_name = _("Public Message")
            self.icon_name = "broadcasts-symbolic"
            return

        if self.is_outgoing and (len(readers) > 1):
            self.display_name = ngettext(
                "{} Reader",
                "{} Readers",
                len(readers),
            ).format(len(readers))
            self.icon_name = "contacts-symbolic"
            return

        self.show_initials = True
        self.profile = Profile.of(
            readers[0] if (self.is_outgoing and readers) else msg.author
        )

        self._bindings = (
            Property.bind(self.profile, "name", self, "display-name"),
            Property.bind(self.profile, "image", self, "profile-image"),
        )

    def trash(self):
        """Move `self` to the trash."""
        from .store import settings_add

        if not self._message:
            return

        settings_add(
            "trashed-messages",
            f"{get_ident(self._message)} {datetime.now(UTC).date().isoformat()}",
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
        from .store import broadcasts, inbox, sent, settings_add

        if not self._message:
            return

        settings_add("deleted-messages", get_ident(self._message))

        envelopes_dir = self._get_data_dir("envelopes", self._message)
        messages_dir = self._get_data_dir("messages", self._message)

        for child in self._message, *self._message.children:
            (envelopes_dir / f"{child.ident}.json").unlink(missing_ok=True)
            (messages_dir / child.ident).unlink(missing_ok=True)

        (
            sent
            if self._message.author == client.user.address
            else broadcasts
            if self._message.is_broadcast
            else inbox
        ).remove(get_ident(self._message))
        self.restore()
        self.set_from_message(None)

    async def discard(self):
        """Discard `self` and its children."""
        from .store import outbox, sent

        if not self._message:
            return

        # TODO: Better UX, cancellation?
        if isinstance(self._message, model.OutgoingMessage) and self._message.sending:
            Notifier.send(_("Cannot discard message while sending"))
            return

        outbox.remove(ident := get_ident(self._message))
        with suppress(ValueError):
            sent.remove(ident)

        failed = False
        for msg in self._message, *self._message.children:
            try:
                await messages.delete(msg.ident)
            except WriteError:  # noqa: PERF203
                if not failed:
                    Notifier.send(_("Failed to discard message"))

                failed = True
                continue

        await outbox.update()
        await sent.update()

    def mark_read(self):
        """Mark a message as read.

        Does nothing if `message.new` is already `False`.
        """
        from .store import settings_discard

        if not self.new:
            return

        self.new = False

        if not self._message:
            return

        self._message.new = False
        settings_discard("unread-messages", get_ident(self._message))

    def _update_trashed_state(self):
        self.can_trash = not self.trashed
        self.can_reply = self.can_discard or self.can_trash
        self.notify("trashed")

    @staticmethod
    def _get_data_dir(name: str, message: model.Message) -> Path:
        host, local = message.author.host_part, message.author.local_part
        suffix = "broadcasts" if message.is_broadcast else ""
        return core.data_dir / name / host / local / suffix


async def send(
    readers: Iterable[Address],
    subject: str,
    body: str,
    subject_id: str | None = None,
    attachments: Iterable[OutgoingAttachment] = (),
):
    """Send a message to `readers`.

    If `readers` is empty, send a broadcast.

    `subject_id` is an optional thread that the message is a part of.

    `attachments` is a dictionary of `Gio.File`s and filenames.
    """
    from .store import outbox, sent

    Notifier().sending = True

    files = dict[model.AttachmentProperties, bytes]()
    for attachment in attachments:
        try:
            _success, data, _etag = await cast(
                "Awaitable[tuple[bool, bytes, str]]",
                attachment.file.load_contents_async(),
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
        message := model.OutgoingMessage(
            readers=list(readers),
            subject=subject,
            body=body,
            subject_id=subject_id,
            files=files,
        )
    )

    try:
        await messages.send(message)
    except WriteError:
        outbox.remove(message.ident)
        Notifier.send(_("Failed to send message"))
        Notifier().sending = False
        raise

    sent.add(message)
    Notifier().sending = False
