# content_view.py
#
# Authors: kramo
# Copyright 2025 Mercata Sagl
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from openemail import PREFIX, notifier, run_task, settings
from openemail.mail import (
    address_book,
    broadcasts,
    drafts,
    inbox,
    is_syncing,
    outbox,
    profiles,
    update_user_profile,
    user,
)

from .compose_dialog import MailComposeDialog
from .contacts_page import MailContactsPage
from .drafts_page import MailDraftsPage
from .messages_page import MailMessagesPage
from .navigation_row import MailNavigationRow
from .profile_settings import MailProfileSettings


@Gtk.Template(resource_path=f"{PREFIX}/gtk/content-view.ui")
class MailContentView(Adw.BreakpointBin):
    """The main content of the application."""

    __gtype_name__ = "MailContentView"

    split_view: Adw.OverlaySplitView = Gtk.Template.Child()

    sidebar: Gtk.ListBox = Gtk.Template.Child()
    contacts_sidebar: Gtk.ListBox = Gtk.Template.Child()
    profile_settings: MailProfileSettings = Gtk.Template.Child()

    broadcasts_page: MailMessagesPage = Gtk.Template.Child()
    inbox_page: MailMessagesPage = Gtk.Template.Child()
    outbox_page: MailMessagesPage = Gtk.Template.Child()
    drafts_page: MailDraftsPage = Gtk.Template.Child()
    trash_page: MailMessagesPage = Gtk.Template.Child()
    contacts_page: MailContactsPage = Gtk.Template.Child()

    content_child_name = GObject.Property(type=str, default="inbox")
    profile_stack_child_name = GObject.Property(type=str, default="loading")
    profile_image = GObject.Property(type=Gdk.Paintable)

    compose_dialog: MailComposeDialog = Gtk.Template.Child()

    _image_binding: GObject.Binding | None = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sidebar.select_row(self.sidebar.get_row_at_index(1))

    def load_content(self, first_sync: bool = True, periodic: bool = False) -> None:
        """Populate the content view by fetching the local user's data.

        Shows a placeholder page while loading if `first_sync` is set to True.
        Otherwise, a toast is presented at the start and end.
        """
        if periodic and (interval := settings.get_uint("sync-interval")):
            GLib.timeout_add_seconds(
                interval or 60,
                self.load_content,
                False,
                True,
            )

            # The user chose manual sync, check again in a minute
            if not interval:
                return

            # Assume that nobody is logged in, skip sync for now
            if not settings.get_string("address"):
                return

        if not first_sync:
            if is_syncing():
                notifier.send(_("Sync already running"))
                return

            notifier.send(_("Syncing…"))

        def update_address_book_cb(success: bool) -> None:
            self.contacts_page.content.loading = False

            if not success:
                return

            run_task(address_book.update_profiles())
            run_task(
                broadcasts.update(),
                lambda _: self.broadcasts_page.content.set_property("loading", False),
            )
            run_task(
                inbox.update(),
                lambda _: self.inbox_page.content.set_property("loading", False),
            )
            run_task(
                outbox.update(),
                lambda _: self.outbox_page.content.set_property("loading", False),
            )

        self.contacts_page.content.loading = True
        self.broadcasts_page.content.loading = True
        self.inbox_page.content.loading = True
        self.outbox_page.content.loading = True
        run_task(address_book.update(), update_address_book_cb)
        run_task(drafts.update())

        def update_user_profile_cb(success: bool) -> None:
            if not success:
                return

            profile = profiles[user.address]

            if self._image_binding:
                self._image_binding.unbind()

            self._image_binding = profile.bind_property(
                "image",
                self,
                "profile-image",
                GObject.BindingFlags.SYNC_CREATE,
            )

            self.profile_settings.profile = profile.profile
            self.profile_stack_child_name = "profile"

        self.profile_stack_child_name = "spinner"
        run_task(update_user_profile(), update_user_profile_cb)

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: MailNavigationRow | None) -> None:
        if not row:
            return

        self.contacts_sidebar.unselect_all()
        self.sidebar.select_row(row)

        self.content_child_name = (
            "broadcasts",
            "inbox",
            "outbox",
            "drafts",
            "trash",
        )[row.get_index()]

        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    @Gtk.Template.Callback()
    def _on_contacts_selected(self, _obj: Any, row: MailNavigationRow | None) -> None:
        if not row:
            return

        self.sidebar.unselect_all()
        self.contacts_sidebar.select_row(row)

        self.content_child_name = "contacts"

        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    @Gtk.Template.Callback()
    def _on_profile_button_clciked(self, *_args: Any) -> None:
        self.profile_settings.present(self)
