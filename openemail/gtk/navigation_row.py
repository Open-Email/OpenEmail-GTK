# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo


from gi.repository import Adw, Gtk

import openemail as app
from openemail import PREFIX, Message, Profile, Property


@Gtk.Template.from_resource(f"{PREFIX}/navigation-row.ui")
class NavigationRow(Gtk.ListBoxRow):
    """An navigation item in the main sidebar with a counter."""

    __gtype_name__ = "NavigationRow"

    counter = Property(str)
    separator = Property(bool)

    _page: Adw.ViewStackPage

    @Property(Adw.ViewStackPage)
    def page(self) -> Adw.ViewStackPage:
        """The `Adw.ViewStackPage` that `self` represents."""
        return self._page

    @page.setter
    def page(self, page: Adw.ViewStackPage):  # HACK
        self._page = page

        if not (content := getattr(self._page.props.child, "content", None)):
            return

        def update_counter(*_args):
            count = 0
            for item in content.model:
                match item:
                    case Profile():
                        count += int(item.contact_request)
                    case Message():
                        count += int(item.unread or bool(item.draft_id))

            self.counter = str(count or "")

        content.model.connect("items-changed", update_counter)
        for key in ("unread-messages", "contact-requests"):
            app.settings.connect(f"changed::{key}", update_counter)
        update_counter()
