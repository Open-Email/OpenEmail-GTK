# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from abc import abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import UTC, datetime
from gettext import ngettext
from typing import Any, Self, cast, override

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

import openemail as app
from openemail import PREFIX

from . import Property, tasks
from .core import client, messages, model
from .core.model import Address, WriteError
from .profile import Profile


def get_unique_id(msg: model.Message, /) -> str:
    """Get a globally unique identifier for `msg`."""
    return f"{msg.author.host_part} {msg.ident}"


class Attachment(GObject.Object):
    """An file attached to a Mail/HTTPS message."""

    __gtype_name__ = __qualname__

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

    __gtype_name__ = __qualname__

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
                    ",".join((
                        Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME,
                        Gio.FILE_ATTRIBUTE_TIME_MODIFIED,
                        Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE,
                        Gio.FILE_ATTRIBUTE_STANDARD_ICON,
                        Gio.FILE_ATTRIBUTE_STANDARD_SIZE,
                    )),
                    Gio.FileQueryInfoFlags.NONE,
                    GLib.PRIORITY_DEFAULT,
                ),
            )
        except GLib.Error as error:
            e = "Could not create attachment: File missing required attributes"
            raise ValueError(e) from error

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

    __gtype_name__ = __qualname__

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
        notification = _("Failed to download attachment")

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
            app.notifier.send(notification)
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
            app.notifier.send(notification)
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


class Message(Gio.SimpleActionGroup):
    """A Mail/HTTPS message."""

    __gtype_name__ = __qualname__

    unique_id = Property(str)
    author = Property(str)
    original_author = Property(str)
    date = Property(int)
    subject = Property(str)
    subject_id = Property(str)
    readers = Property(str)
    attachments = Property(Gio.ListStore)
    body = Property(str)
    is_broadcast = Property(bool)

    profile = Property(Profile)
    display_date = Property(str)
    display_datetime = Property(str)
    display_readers = Property(str)

    list_name = Property(str)
    list_image = Property(Gdk.Paintable)
    list_icon_name = Property(str)
    list_initials = Property(bool)

    is_outgoing, is_incoming = Property(bool), Property(bool, default=True)
    is_draft = Property(bool)
    different_author = Property(bool)
    has_other_readers = Property(bool)
    can_reply = Property(bool)
    can_trash = Property(bool)
    can_discard = Property(bool)
    can_mark_unread = Property(bool, default=True)

    _bindings: tuple[GObject.Binding, ...] = ()
    _msg: model.Message | None = None

    @Property(bool)
    def unread(self) -> bool:
        """Whether the message is unread by the user."""
        from . import store

        return self.unique_id in store.settings.get_strv("unread-messages")

    @unread.setter
    def unread(self, unread: bool):
        if not self._msg:
            return

        self._msg.new = unread

        from . import store

        if unread:
            store.settings_add("unread-messages", self.unique_id)
        else:
            store.settings_discard("unread-messages", self.unique_id)

    @Property(bool)
    def trashed(self) -> bool:
        """Whether the item is in the trash."""
        if self.can_discard or (not self._msg):
            return False

        from . import store

        return any(
            msg.rsplit(maxsplit=1)[0] == self.unique_id
            for msg in store.settings.get_strv("trashed-messages")
        )

    def __init__(self, msg: model.Message | None = None, /, **kwargs: Any):
        super().__init__(**kwargs)

        self.attachments = Gio.ListStore.new(Attachment)
        self.set_from_message(msg)

        template = Gtk.ConstantExpression.new_for_value(self)
        unread_active = Gtk.ClosureExpression.new(
            bool,
            lambda _, can_mark_unread, unread: can_mark_unread and not unread,
            (
                Gtk.PropertyExpression.new(Message, template, "can-mark-unread"),
                Gtk.PropertyExpression.new(Message, template, "unread"),
            ),
        )

        self._add_action("read", lambda: setattr(self, "unread", False), "unread")
        self._add_action("unread", lambda: setattr(self, "unread", True), unread_active)
        self._add_action("trash", lambda: self.trash(notify=True), "can-trash")
        self._add_action("restore", lambda: self.restore(notify=True), "trashed")
        self._add_action("discard", lambda: tasks.create(self.discard()), "can-discard")

    def __hash__(self) -> int:
        return hash(self.unique_id) if self._msg else super().__hash__()

    def __eq__(self, value: object, /) -> bool:
        return (
            self.unique_id == value.unique_id
            if isinstance(value, Message)
            else super().__eq__(value)
        )

    def __ne__(self, value: object, /) -> bool:
        return (
            self.unique_id != value.unique_id
            if isinstance(value, Message)
            else super().__ne__(value)
        )

    def set_from_message(self, msg: model.Message | None, /):
        """Set the properties of `self` from `msg`."""
        self._msg = msg

        if not msg:
            return

        self.unique_id = get_unique_id(msg)

        local_date = msg.date.astimezone(datetime.now(UTC).astimezone().tzinfo)
        self.date = int(local_date.timestamp())
        self.display_date = local_date.strftime("%x")
        # Localized date format, time in H:M
        self.display_datetime = _("{} at {}").format(
            self.display_date, local_date.strftime("%H:%M")
        )

        self.subject = msg.subject
        self.body = msg.body or ""
        self.unread = msg.new
        self.is_broadcast = msg.is_broadcast

        self.is_outgoing = msg.author == client.user.address
        self.is_incoming = not self.is_outgoing
        self._update_trashed_state()

        self.author = msg.author
        self.original_author = f"{_('Original Author:')} {msg.original_author}"
        self.different_author = msg.author != msg.original_author

        readers = tuple(r for r in msg.readers if r != client.user.address)
        self.display_readers = (
            _("Public Message")
            if self.is_broadcast
            # Translators: Readers will be appended to this string"
            else f"{_('Readers:')} {', '.join(Profile.of(r).name for r in readers)}"
            if readers
            else None
        )
        self.has_other_readers = bool(self.display_readers)
        self.readers = ", ".join(
            readers if self.is_outgoing else (*readers, msg.author)
        )

        self.attachments.remove_all()
        for name, parts in msg.attachments.items():
            self.attachments.append(IncomingAttachment(name, parts))

        self.profile = Profile.of(msg.author)

        match msg:
            case model.IncomingMessage() | model.OutgoingMessage():
                self.subject_id = msg.subject_id
            case model.DraftMessage():
                self.is_draft = True

        for binding in self._bindings:
            binding.unbind()

        self._bindings = ()

        self.list_image, self.list_initials = None, False

        if not (msg.readers or msg.is_broadcast):
            self.list_name = _("No Readers")
            self.list_icon_name = "public-access-symbolic"
            return

        if self.is_outgoing and msg.is_broadcast:
            self.list_name = _("Public Message")
            self.list_icon_name = "broadcasts-symbolic"
            return

        if self.is_outgoing and (len(readers) > 1):
            self.list_name = ngettext(
                "{} Reader",
                "{} Readers",
                len(readers),
            ).format(len(readers))
            self.list_icon_name = "contacts-symbolic"
            return

        self.list_initials = True

        p = Profile.of(readers[0]) if (self.is_outgoing and readers) else self.profile
        self._bindings = (
            Property.bind(p, "name", self, "list-name"),
            Property.bind(p, "image", self, "list-image"),
        )

    def trash(self, *, notify: bool = False):
        """Move `self` to the trash.

        If `notify` is `True`, send a confirmation notification.
        """
        if not self._msg:
            return

        from . import store

        store.settings_add(
            "trashed-messages",
            f"{self.unique_id} {datetime.now(UTC).date().isoformat()}",
        )

        self._update_trashed_state()

        if notify:
            app.notifier.send(_("Message moved to trash"), undo=self.restore)

    def restore(self, *, notify: bool = False):
        """Restore `self` from the trash.

        If `notify` is `True`, send a confirmation notification.
        """
        if not self._msg:
            return

        from . import store

        store.settings.set_strv(
            "trashed-messages",
            tuple(
                msg
                for msg in store.settings.get_strv("trashed-messages")
                if msg.rsplit(maxsplit=1)[0] != self.unique_id
            ),
        )

        self._update_trashed_state()

        if notify:
            app.notifier.send(_("Message restored"), undo=self.trash)

    def delete(self):
        """Remove `self` from the trash."""
        if not self._msg:
            return

        from . import store

        model = (
            store.sent
            if self._msg.author == client.user.address
            else store.broadcasts
            if self._msg.is_broadcast
            else store.inbox
        )

        for child in self._msg, *self._msg.children:
            messages.remove_from_disk(child)

        store.settings_add("deleted-messages", self.unique_id)
        model.remove(self.unique_id)
        self.restore()  # Since it is deleted, there is no reason to keep it in trash
        self.set_from_message(None)

    async def discard(self):
        """Discard `self` and its children."""
        if not (
            self._msg
            and (application := cast("Gtk.Application", Gio.Application.get_default()))
            and (window := application.props.active_window)
        ):
            return

        builder = Gtk.Builder.new_from_resource(f"{PREFIX}/dialogs.ui")
        dialog = cast("Adw.AlertDialog", builder.get_object("discard_dialog"))

        response = await cast("Awaitable[str]", dialog.choose(window))
        if response != "discard":
            return

        # TODO: Better UX, cancellation?
        if isinstance(self._msg, model.OutgoingMessage) and self._msg.sending:
            app.notifier.send(_("Cannot discard message while sending"))
            return

        from . import store

        store.outbox.remove(ident := self.unique_id)
        with suppress(ValueError):
            store.sent.remove(ident)

        failed = False
        for msg in self._msg, *self._msg.children:
            try:
                await messages.delete(msg.ident)
            except WriteError:  # noqa: PERF203
                if not failed:
                    app.notifier.send(_("Failed to discard message"))

                failed = True
                continue

        await store.outbox.update()
        await store.sent.update()

    def _update_trashed_state(self):
        self.can_trash = not (self.can_discard or self.trashed)
        self.can_reply = self.can_discard or self.can_trash
        self.notify("trashed")

    def _add_action(
        self,
        name: str,
        func: Callable[..., Any],
        bind_to: str | Gtk.Expression | None = None,
    ):
        action = Gio.SimpleAction.new(name)
        action.connect("activate", lambda *_: func())

        match bind_to:
            case str():
                Property.bind(self, bind_to, action, "enabled")
            case Gtk.Expression():
                bind_to.bind(action, "enabled")

        self.add_action(action)


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
    app.notifier.sending = True

    files = dict[model.AttachmentProperties, bytes]()
    for attachment in attachments:
        try:
            _success, data, _etag = await cast(
                "Awaitable[tuple[bool, bytes, str]]",
                attachment.file.load_contents_async(),
            )
        except GLib.Error as error:
            app.notifier.send(_("Failed to send message"))
            app.notifier.sending = False
            raise WriteError from error

        files[
            model.AttachmentProperties(
                name=attachment.name,
                ident=model.generate_id(client.user.address),
                type=attachment.type,
                modified=attachment.modified,
            )
        ] = data

    from . import store

    store.outbox.add(
        msg := model.OutgoingMessage(
            readers=list(readers),
            subject=subject,
            body=body,
            subject_id=subject_id,
            files=files,
        )
    )

    try:
        await messages.send(msg)
    except WriteError:
        store.outbox.remove(msg.ident)
        app.notifier.send(_("Failed to send message"))
        app.notifier.sending = False
        raise

    store.sent.add(msg)
    app.notifier.sending = False
