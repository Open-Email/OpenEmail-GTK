# message_view.py
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

from typing import Any, Callable

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from openemail import shared
from openemail.core.crypto import decrypt_xchacha20poly1305
from openemail.core.message import Message
from openemail.core.network import delete_message, request

from .profile_view import MailProfileView


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/message-view.ui")
class MailMessageView(Adw.Bin):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = "MailMessageView"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()

    reply_button: Gtk.Button = Gtk.Template.Child()
    attachments: Gtk.ListBox = Gtk.Template.Child()

    profile_dialog: Adw.Dialog = Gtk.Template.Child()
    profile_view: MailProfileView = Gtk.Template.Child()
    confirm_discard_dialog: Adw.AlertDialog = Gtk.Template.Child()

    visible_child_name = GObject.Property(type=str, default="empty")

    message: Message | None = None
    attachment_messages: dict[Adw.ActionRow, list[Message]]

    name = GObject.Property(type=str)
    date = GObject.Property(type=str)
    subject = GObject.Property(type=str)
    body = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)
    readers = GObject.Property(type=str)

    author_is_self = GObject.Property(type=bool, default=False)
    can_trash = GObject.Property(type=bool, default=False)
    can_restore = GObject.Property(type=bool, default=False)
    can_reply = GObject.Property(type=bool, default=False)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    undo: dict[Adw.Toast, Callable[[], Any]]

    def __init__(self, message: Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.attachment_messages = {}
        self.undo = {}

        def undo(*_args: Any) -> bool:
            if not self.undo:
                return False

            toast, callback = self.undo.popitem()
            toast.dismiss()
            callback()

            return True

        self.add_controller(
            controller := Gtk.ShortcutController(
                scope=Gtk.ShortcutScope.GLOBAL,
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("Delete|KP_Delete"),
                Gtk.CallbackAction.new(
                    lambda *_: not (
                        self._discard
                        if self.author_is_self
                        else self._trash
                        if self.can_trash
                        else self._restore
                    )()
                ),
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>z"),
                Gtk.CallbackAction.new(undo),
            )
        )

        if message:
            self.set_from_message(message)

    def set_from_message(self, message: Message) -> None:
        """Update properties of the view from `message`."""
        self.visible_child_name = "message"

        self.message = message
        self.date = message.envelope.date.strftime("%x")
        self.subject = message.envelope.subject
        self.body = message.body

        self.can_reply = True

        self.author_is_self = shared.user and (
            message.envelope.author == shared.user.address
        )

        self.can_trash = (not self.author_is_self) and (
            message.envelope.message_id
            not in shared.settings.get_strv("trashed-message-ids")
        )
        self.can_restore = not (self.can_trash or self.author_is_self)

        if self._name_binding:
            self._name_binding.unbind()
        self._name_binding = shared.profiles[message.envelope.author].bind_property(
            "name", self, "name", GObject.BindingFlags.SYNC_CREATE
        )

        if self._image_binding:
            self._image_binding.unbind()
        self._image_binding = shared.profiles[message.envelope.author].bind_property(
            "image", self, "profile-image", GObject.BindingFlags.SYNC_CREATE
        )

        self.attachments.remove_all()
        self.attachment_messages = {}
        for name, parts in message.attachments.items():
            row = Adw.ActionRow(title=name, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name("mail-attachment-symbolic"))
            self.attachment_messages[row] = parts
            self.attachments.append(row)

        if message.envelope.is_broadcast:
            self.readers = _("Broadcast")
            return

        self.readers = _("Readers: ")
        self.readers += str(
            shared.profiles[shared.user.address].name if shared.user else _("Me")
        )

        for reader in message.envelope.readers:
            if shared.user and reader == shared.user.address:
                continue

            self.readers += f", {profile.name if (profile := shared.profiles.get(reader)) else reader}"

    @Gtk.Template.Callback()
    def _show_profile_dialog(self, *_args: Any) -> None:
        self.profile_view.profile = (
            shared.profiles[self.message.envelope.author].profile
            if self.message
            else None
        )
        self.profile_dialog.present(self)

    @Gtk.Template.Callback()
    def _open_attachment(self, _obj: Any, row: Adw.ActionRow) -> None:
        if not (parts := self.attachment_messages.get(row)):
            return

        async def save() -> None:
            try:
                gfile = await Gtk.FileDialog(  # type: ignore
                    initial_name=row.get_title(),
                    initial_folder=Gio.File.new_for_path(downloads)
                    if (
                        downloads := GLib.get_user_special_dir(
                            GLib.UserDirectory.DIRECTORY_DOWNLOAD
                        )
                    )
                    else None,
                ).save(win if isinstance(win := self.get_root(), Gtk.Window) else None)
            except GLib.Error:
                return

            data = b""
            for part in parts:
                if not (
                    (url := part.attachment_url)
                    and (response := await request(url, shared.user))
                ):
                    return

                with response:
                    contents = response.read()

                if (
                    part
                    and (not part.envelope.is_broadcast)
                    and part.envelope.access_key
                ):
                    try:
                        contents = decrypt_xchacha20poly1305(
                            contents, part.envelope.access_key
                        )
                    except ValueError:
                        return

                data += contents

            try:
                stream = gfile.replace(
                    None,
                    True,
                    Gio.FileCreateFlags.REPLACE_DESTINATION,
                )
            except GLib.Error:
                return

            await stream.write_bytes_async(GLib.Bytes.new(data), GLib.PRIORITY_DEFAULT)
            await stream.close_async(GLib.PRIORITY_DEFAULT)

        shared.run_task(save())

    @Gtk.Template.Callback()
    def _trash(self, *_args: Any) -> None:
        if not self.message:
            return

        shared.trash_message(message_id := self.message.envelope.message_id)
        self.__add_to_undo(
            _("Message moved to trash"),
            lambda: shared.restore_message(message_id),
        )

    @Gtk.Template.Callback()
    def _restore(self, *_args: Any) -> None:
        if not self.message:
            return

        shared.restore_message(message_id := self.message.envelope.message_id)
        self.__add_to_undo(
            _("Message restored"),
            lambda: shared.trash_message(message_id),
        )

    @Gtk.Template.Callback()
    def _discard(self, *_args: Any) -> None:
        self.confirm_discard_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_discard(self, _obj: Any, response: str) -> None:
        if response != "discard":
            return

        if not (self.message and shared.user):
            return

        shared.run_task(
            delete_message(self.message.envelope.message_id, shared.user),
            lambda: shared.run_task(shared.update_outbox()),
        )

    def __add_to_undo(self, title: str, undo: Callable[[], Any]) -> None:
        self.undo[
            toast := Adw.Toast(
                title=title,
                priority=Adw.ToastPriority.HIGH,
                button_label=_("Undo"),
            )
        ] = undo
        toast.connect(
            "button-clicked",
            lambda *_: self.undo.pop(toast, lambda: None)(),
        )
        self.toast_overlay.add_toast(toast)
