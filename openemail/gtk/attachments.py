# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any, override

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX


@Gtk.Template.from_resource(f"{PREFIX}/attachments.ui")
class Attachments(Adw.Bin):
    """A grid of files attached to a message."""

    __gtype_name__ = "Attachments"

    model = GObject.Property(type=Gio.ListStore)

    @Gtk.Template.Callback()
    def _open(self, _obj, pos: int):
        if not (attachment := self.model.get_item(pos)):
            return

        attachment.open(self)


class RemoveAttachmentButton(Gtk.Button):
    """A button in a list of attachments, used to remove one."""

    __gtype_name__ = "RemoveAttachmentButton"

    position = GObject.Property(type=int)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.props.icon_name = "remove-symbolic"
        self.props.tooltip_text = _("Remove")

    @override
    def do_clicked(self):
        if not (attachments := self.get_ancestor(Attachments)):
            return

        attachments.model.remove(self.position)
