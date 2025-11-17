# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from gi.repository import Adw, Gio, Gtk

from openemail import PREFIX, Property
from openemail.message import Attachment, IncomingAttachment, OutgoingAttachment


@Gtk.Template.from_resource(f"{PREFIX}/attachments.ui")
class Attachments(Adw.Bin):
    """A grid of files attached to a message."""

    __gtype_name__ = __qualname__

    model = Property(Gio.ListStore)

    @Gtk.Template.Callback()
    def _open(self, _obj, pos: int):
        match attachment := self.model.get_item(pos):
            case OutgoingAttachment():
                attachment.open()
            case IncomingAttachment():
                attachment.open(self)


@Gtk.Template.from_resource(f"{PREFIX}/attachments-item.ui")
class AttachmentsItem(Adw.Bin):
    """A widget representing an attachment in `Attachments`."""

    __gtype_name__ = __qualname__

    attachment = Property(Attachment)

    @Gtk.Template.Callback()
    def _remove(self, *_args):
        if not (attachments := self.get_ancestor(Attachments)):
            return

        found, pos = attachments.model.find(self.attachment)
        if found:
            attachments.model.remove(pos)
