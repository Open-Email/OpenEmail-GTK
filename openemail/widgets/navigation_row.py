# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo


from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import PREFIX, settings
from openemail.mail import Message, Profile


@Gtk.Template.from_resource(f"{PREFIX}/gtk/navigation-row.ui")
class NavigationRow(Gtk.ListBoxRow):
    """An navigation item in the main sidebar with a counter."""

    __gtype_name__ = "NavigationRow"

    counter = GObject.Property(type=str)

    _page: Adw.ViewStackPage

    @GObject.Property(type=Adw.ViewStackPage)
    def page(self) -> Adw.ViewStackPage:
        """Get the `Adw.ViewStackPage` that `self` represents."""
        return self._page

    @page.setter
    def page(self, page: Adw.ViewStackPage) -> None:
        self._page = page

        if not (content := getattr(self._page.props.child, "content", None)):
            return

        model = content.model.props.model.props.model.props.model

        def update_counter(*_args: Any) -> None:
            count = 0
            for item in model:
                if isinstance(item, Profile):
                    count += int(item.contact_request)

                elif isinstance(item, Message):
                    count += int(item.unread or bool(item.draft_id))

            self.counter = str(count or "")

        model.connect("items-changed", update_counter)
        settings.connect("changed::unread-messages", update_counter)
        settings.connect("changed::contact-requests", update_counter)
        update_counter()
