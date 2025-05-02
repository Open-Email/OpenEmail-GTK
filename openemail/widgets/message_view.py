# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any, Callable

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from openemail import PREFIX, run_task
from openemail.mail import Attachment, Message, Profile

from .message_body import MessageBody
from .profile_view import ProfileView


@Gtk.Template(resource_path=f"{PREFIX}/gtk/message-view.ui")
class MessageView(Adw.Bin):
    """A view displaying metadata about, and the contents of a message."""

    __gtype_name__ = "MessageView"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()

    reply_button: Gtk.Button = Gtk.Template.Child()
    message_body: MessageBody = Gtk.Template.Child()
    attachments_list: Gtk.ListBox = Gtk.Template.Child()

    profile_dialog: Adw.Dialog = Gtk.Template.Child()
    profile_view: ProfileView = Gtk.Template.Child()
    confirm_discard_dialog: Adw.AlertDialog = Gtk.Template.Child()

    visible_child_name = GObject.Property(type=str, default="empty")

    attachments: dict[Adw.ActionRow, Attachment]
    undo: dict[Adw.Toast, Callable[[], Any]]

    _message: Message | None = None

    @GObject.Property(type=Message)
    def message(self) -> Message | None:
        """Get the `Message` that `self` represents."""
        return self._message or Message()

    @message.setter
    def message(self, message: Message | None) -> None:
        self._message = message

        if not message:
            self.visible_child_name = "empty"
            return

        self.visible_child_name = "message"

        self.attachments_list.remove_all()
        self.attachments = {}
        for a in message.attachments:
            row = Adw.ActionRow(title=a.name, activatable=True, use_markup=False)  # type: ignore
            row.add_prefix(Gtk.Image.new_from_icon_name("mail-attachment-symbolic"))
            self.attachments[row] = a  # type: ignore
            self.attachments_list.append(row)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.attachments = {}
        self.undo = {}

        def undo(*_args: Any) -> bool:
            if not self.undo:
                return False

            toast, callback = self.undo.popitem()
            toast.dismiss()
            callback()

            return True

        controller = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<primary>z"),
                Gtk.CallbackAction.new(undo),
            )
        )

        self.add_controller(controller)

    @Gtk.Template.Callback()
    def _show_profile_dialog(self, *_args: Any) -> None:
        self.profile_view.profile = (
            Profile.of(message.author)
            if (self.message and (message := self.message.message))
            else None
        )
        self.profile_dialog.present(self)

    @Gtk.Template.Callback()
    def _open_attachment(self, _obj: Any, row: Adw.ActionRow) -> None:
        if not (attachment := self.attachments.get(row)):
            return

        async def save() -> None:
            try:
                gfile = await Gtk.FileDialog(  # type: ignore
                    initial_name=row.props.title,
                    initial_folder=Gio.File.new_for_path(downloads)
                    if (
                        downloads := GLib.get_user_special_dir(
                            GLib.UserDirectory.DIRECTORY_DOWNLOAD
                        )
                    )
                    else None,
                ).save(win if isinstance(win := self.props.root, Gtk.Window) else None)
            except GLib.Error:
                return

            if not (data := await attachment.download()):
                return

            try:
                stream = gfile.replace(
                    None, True, Gio.FileCreateFlags.REPLACE_DESTINATION
                )
                await stream.write_bytes_async(
                    GLib.Bytes.new(data), GLib.PRIORITY_DEFAULT
                )
                await stream.close_async(GLib.PRIORITY_DEFAULT)
            except GLib.Error:
                return

        run_task(save())

    @Gtk.Template.Callback()
    def _trash(self, *_args: Any) -> None:
        if not self.message:
            return

        (message := self.message).trash()
        self._add_to_undo(_("Message moved to trash"), lambda: message.restore())

    @Gtk.Template.Callback()
    def _restore(self, *_args: Any) -> None:
        if not self.message:
            return

        (message := self.message).restore()
        self._add_to_undo(_("Message restored"), lambda: message.trash())

    @Gtk.Template.Callback()
    def _discard(self, *_args: Any) -> None:
        self.confirm_discard_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_discard(self, _obj: Any, response: str) -> None:
        if (response != "discard") or (not self.message):
            return

        run_task(self.message.discard())

    def _add_to_undo(self, title: str, undo: Callable[[], Any]) -> None:
        toast = Adw.Toast(
            title=title,
            priority=Adw.ToastPriority.HIGH,
            button_label=_("Undo"),
        )
        toast.connect(
            "button-clicked",
            lambda *_: self.undo.pop(toast, lambda: None)(),
        )

        self.undo[toast] = undo
        self.toast_overlay.add_toast(toast)
