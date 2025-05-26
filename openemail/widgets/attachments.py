# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GObject, Gtk

from openemail import PREFIX


@Gtk.Template(resource_path=f"{PREFIX}/gtk/attachments.ui")
class Attachments(Adw.Bin):
    """A grid of files attached to a message."""

    __gtype_name__ = "Attachments"

    model = GObject.Property(type=Gio.ListModel)

    @Gtk.Template.Callback()
    def _open(self, _obj: Any, pos: int) -> None:
        if not (attachment := self.model.get_item(pos)):
            return

        attachment.open()
