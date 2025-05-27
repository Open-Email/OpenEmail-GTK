# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from gi.repository import GObject, Gtk

from openemail import PREFIX


@Gtk.Template.from_resource(f"{PREFIX}/gtk/navigation-row.ui")
class NavigationRow(Gtk.ListBoxRow):
    """An item in the main sidebar."""

    __gtype_name__ = "NavigationRow"

    label = GObject.Property(type=str)
    icon_name = GObject.Property(type=str)
