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

from gi.repository import Adw, Gdk, GObject, Gtk

from openemail import shared
from openemail.gtk.contacts_page import MailContactsPage
from openemail.gtk.messages_page import MailMessagesPage
from openemail.gtk.navigation_row import MailNavigationRow
from openemail.gtk.profile_view import MailProfileView


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/content-view.ui")
class MailContentView(Adw.BreakpointBin):
    """The main content of the application."""

    __gtype_name__ = "MailContentView"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    split_view: Adw.OverlaySplitView = Gtk.Template.Child()

    sidebar: Gtk.ListBox = Gtk.Template.Child()
    contacts_sidebar: Gtk.ListBox = Gtk.Template.Child()
    profile_dialog: Adw.Dialog = Gtk.Template.Child()
    profile_view: MailProfileView = Gtk.Template.Child()  # type: ignore

    empty_status_page: Adw.StatusPage = Gtk.Template.Child()

    broadcasts_page: MailMessagesPage = Gtk.Template.Child()  # type: ignore
    inbox_page: MailMessagesPage = Gtk.Template.Child()  # type: ignore
    outbox_page: MailMessagesPage = Gtk.Template.Child()  # type: ignore
    contacts_page: MailContactsPage = Gtk.Template.Child()  # type: ignore

    syncing_toast: Adw.Toast | None = None

    content_child_name = GObject.Property(type=str, default="inbox")
    profile_stack_child_name = GObject.Property(type=str, default="spinner")
    profile_image = GObject.Property(type=Gdk.Paintable)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sidebar.select_row(self.sidebar.get_row_at_index(1))

    def load_content(self, first_sync: bool = True) -> None:
        """Populate the content view by fetching the local user's data.

        Shows a placeholder page while loading if `first_sync` is set to True.
        Otherwise, a toast is presented at the start and end.
        """
        if not first_sync:
            if shared.is_loading():
                if self.syncing_toast:
                    self.syncing_toast.dismiss()

                self.syncing_toast = Adw.Toast(
                    title=_("Sync already running"),
                    priority=Adw.ToastPriority.HIGH,
                )
                self.toast_overlay.add_toast(self.syncing_toast)
                return

            if self.syncing_toast:
                self.syncing_toast.dismiss()

            self.syncing_toast = Adw.Toast(
                title=_("Syncing…"),
                priority=Adw.ToastPriority.HIGH,
            )
            self.toast_overlay.add_toast(self.syncing_toast)

        def update_address_book_cb() -> None:
            self.contacts_page.content.loading = False

            shared.run_task(shared.update_profiles())
            shared.run_task(
                shared.update_broadcasts_list(),
                lambda: self.broadcasts_page.content.set_property("loading", False),
            )
            shared.run_task(
                shared.update_messages_list(),
                lambda: self.inbox_page.content.set_property("loading", False),
            )
            shared.run_task(
                shared.update_outbox(),
                lambda: self.outbox_page.content.set_property("loading", False),
            )

        self.contacts_page.content.loading = True
        self.broadcasts_page.content.loading = True
        self.inbox_page.content.loading = True
        self.outbox_page.content.loading = True
        shared.run_task(shared.update_address_book(), update_address_book_cb)

        def update_user_profile_cb() -> None:
            if not shared.user:
                return

            profile = shared.profiles[shared.user.address]
            self.profile_view.profile = profile.profile
            self.profile_image = self.profile_view.profile_image = profile.image
            self.profile_stack_child_name = "profile"

        self.profile_stack_child_name = "spinner"
        shared.run_task(shared.update_user_profile(), update_user_profile_cb)

    @Gtk.Template.Callback()
    def _on_row_selected(self, _obj: Any, row: MailNavigationRow | None) -> None:  # type: ignore
        if not row:
            return

        self.contacts_sidebar.unselect_all()
        self.sidebar.select_row(row)

        match row.get_index():
            case 0:
                self.content_child_name = "broadcasts"
            case 1:
                self.content_child_name = "inbox"
            case 2:
                self.content_child_name = "outbox"
            case 4:
                self.content_child_name = "trash"
            case _:
                self.empty_status_page.set_title(row.label)
                self.empty_status_page.set_icon_name(row.icon_name)
                self.content_child_name = "placeholder"

        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    @Gtk.Template.Callback()
    def _on_contacts_selected(self, _obj: Any, row: MailNavigationRow | None) -> None:  # type: ignore
        if not row:
            return

        self.sidebar.unselect_all()
        self.contacts_sidebar.select_row(row)

        self.content_child_name = "contacts"

        if self.split_view.get_collapsed():
            self.split_view.set_show_sidebar(False)

    @Gtk.Template.Callback()
    def _on_profile_button_clciked(self, *_args: Any) -> None:
        self.profile_dialog.present(self)

    @Gtk.Template.Callback()
    def _show_sidebar(self, *_args: Any) -> None:
        self.split_view.set_show_sidebar(not self.split_view.get_show_sidebar())
