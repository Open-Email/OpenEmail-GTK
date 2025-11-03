# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GLib, Gtk

from openemail import PREFIX, Property
from openemail.message import IncomingAttachment, OutgoingAttachment


@Gtk.Template.from_resource(f"{PREFIX}/attachments.ui")
class Attachments(Adw.Bin):
    """A grid of files attached to a message."""

    __gtype_name__ = __qualname__

    model = Property(Gio.ListStore)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("attachments", group := Gio.SimpleActionGroup())
        group.add_action_entries(
            (("remove", lambda _action, ident, _data: self._remove(ident), "x"),)
        )

    @Gtk.Template.Callback()
    def _open(self, _obj, pos: int):
        match attachment := self.model.get_item(pos):
            case OutgoingAttachment():
                attachment.open()
            case IncomingAttachment():
                attachment.open(self)

    def _remove(self, ident: GLib.Variant):
        pos = next(i for i, a in enumerate(self.model) if a.ident == ident)  # pyright: ignore[reportAttributeAccessIssue]
        self.model.remove(pos)
