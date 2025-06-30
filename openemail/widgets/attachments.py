# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX


class RemoveAttachmentButton(Gtk.Button):
    """A button in a list of attachments, used to remove one."""

    __gtype_name__ = "RemoveAttachmentButton"

    item = GObject.Property(type=Gtk.ListItem)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.props.icon_name = "remove-symbolic"
        self.props.tooltip_text = _("Remove")

    def do_clicked(self) -> None:
        """Signal emitted when the button has been activated (pressed and released)."""
        if not (
            (overlay := self.props.parent)
            and (list_item := overlay.props.parent)
            and (grid := list_item.props.parent)
            and isinstance(attachments := grid.props.parent, Attachments)
        ):
            return

        attachments.model.remove(self.item.props.position)


@Gtk.Template.from_resource(f"{PREFIX}/attachments.ui")
class Attachments(Adw.Bin):
    """A grid of files attached to a message."""

    __gtype_name__ = "Attachments"

    model = GObject.Property(type=Gio.ListStore)

    @Gtk.Template.Callback()
    def _open(self, _obj: Any, pos: int) -> None:
        if not (attachment := self.model.get_item(pos)):
            return

        attachment.open(self)
