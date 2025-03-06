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

from re import sub
from typing import Any

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk
from nacl.public import SealedBox

from openemail import shared
from openemail.crypto import decrypt_xchacha20poly1305
from openemail.gtk.profile_view import MailProfileView
from openemail.message import Message
from openemail.network import request


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/message-view.ui")
class MailMessageView(Adw.Bin):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = "MailMessageView"

    attachments: Gtk.ListBox = Gtk.Template.Child()

    profile_dialog: Adw.Dialog = Gtk.Template.Child()
    profile_view: MailProfileView = Gtk.Template.Child()  # type: ignore

    visible_child_name = GObject.Property(type=str, default="empty")

    message: Message | None = None
    attachment_messages: dict[Adw.ActionRow, list[Message]]

    name = GObject.Property(type=str)
    date = GObject.Property(type=str)
    subject = GObject.Property(type=str)
    body = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)
    readers = GObject.Property(type=str)

    _name_binding: GObject.Binding | None = None
    _image_binding: GObject.Binding | None = None

    def __init__(self, message: Message | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.attachment_messages = {}

        if message:
            self.set_from_message(message)

    def set_from_message(self, message: Message) -> None:
        """Update properties of the view from `message`."""
        self.visible_child_name = "message"

        self.message = message
        self.date = message.envelope.date.strftime("%x")
        self.subject = message.envelope.subject
        self.body = message.body

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

        async def save(gfile: Gio.File) -> None:
            data = b""
            for part in parts:
                if not (
                    (url := part.attachment_url)
                    and (response := await request(part.attachment_url, shared.user))
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

            stream.write_bytes(GLib.Bytes.new(data))  # type: ignore
            stream.close()

        def save_finish(dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                if not (gfile := dialog.save_finish(result)):
                    return

            except GLib.Error:
                return

            shared.loop.create_task(save(gfile))

        Gtk.FileDialog(
            initial_name=row.get_title(),
            initial_folder=Gio.File.new_for_path(downloads)
            if (
                downloads := GLib.get_user_special_dir(
                    GLib.UserDirectory.DIRECTORY_DOWNLOAD
                )
            )
            else None,
        ).save(
            win if isinstance(win := self.get_root(), Gtk.Window) else None,
            callback=save_finish,
        )
