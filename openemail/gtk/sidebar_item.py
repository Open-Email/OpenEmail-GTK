# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, Gtk

from openemail import Property


class SidebarItem(Adw.SidebarItem):  # pyright: ignore[reportUntypedBaseClass, reportAttributeAccessIssue]
    """An item in the main navigation sidebar."""

    __gtype_name__ = __qualname__

    description = Property[str | None](str)

    model = Property(Gio.ListModel)
    badge_number = Property(int)
    details = Property(Gtk.Widget)

    action_name = Property(str)
    action_label = Property(str)
    action_icon_name = Property(str)

    placeholder_title = Property(str)
    placeholder_description = Property[str | None](str)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        label = Gtk.Label()
        label.add_css_class("dim-label")
        self.props.suffix = Gtk.Revealer(
            child=label, transition_type=Gtk.RevealerTransitionType.CROSSFADE
        )

        Property.bind(self, "badge-number", self.props.suffix, "reveal-child")
        Property.bind(
            self,
            "badge-number",
            label,
            "label",
            lambda _, i: str(i or label.props.label),
        )


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
