# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any, override

from gi.repository import Adw, Gio, Gtk

from openemail import PREFIX, Property
from openemail.message import IncomingAttachment, OutgoingAttachment


@Gtk.Template.from_resource(f"{PREFIX}/attachments.ui")
class Attachments(Adw.Bin):
    """A grid of files attached to a message."""

    __gtype_name__ = "Attachments"

    model = Property(Gio.ListStore)

    @Gtk.Template.Callback()
    def _open(self, _obj, pos: int):
        match attachment := self.model.get_item(pos):
            case OutgoingAttachment():
                attachment.open()
            case IncomingAttachment():
                attachment.open(self)


class RemoveAttachmentButton(Gtk.Button):
    """A button in a list of attachments, used to remove one."""

    __gtype_name__ = "RemoveAttachmentButton"

    position = Property(int)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.props.icon_name = "remove-symbolic"
        self.props.tooltip_text = _("Remove")

    @override
    def do_clicked(self):
        if attachments := self.get_ancestor(Attachments):
            attachments.model.remove(self.position)
