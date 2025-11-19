# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, Gtk

from openemail import Property


class SidebarItem(Adw.SidebarItem):  # pyright: ignore[reportUntypedBaseClass, reportAttributeAccessIssue]
    """An item in the main navigation sidebar.

    `SidebarItem:badge-model` must be a `Gio.ListModel` with `n-items` as a property.
    """

    __gtype_name__ = __qualname__

    description = Property[str | None](str)

    model = Property(Gtk.SingleSelection)
    badge_model = Property(Gio.ListModel)
    details = Property(Gtk.Widget)

    action_name = Property(str)
    action_label = Property(str)
    action_icon_name = Property(str)

    placeholder_title = Property(str)
    placeholder_description = Property[str | None](str)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.props.suffix = Gtk.Label()
        # self.model.bind_property(
        #     "n-items",
        #     self.model,
        #     "label",
        #     GObject.BindingFlags.SYNC_CREATE,
        #     lambda _, i: str(i),
        # )


class FolderSidebarItem(SidebarItem):
    """A sidebar item used by folders of messages."""

    __gtype_name__ = __qualname__

    def __init__(self, **kwargs: Any):
        self.action_name = "compose.new"
        self.action_label = _("New Message")
        self.action_icon_name = "mail-message-new-symbolic"

        self.placeholder_title = _("Empty Folder")
        self.placeholder_description = _(
            "Select another folder or start a conversation"
        )

        super().__init__(**kwargs)
