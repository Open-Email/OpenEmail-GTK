# profile_view.py
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

from openemail.core.client import delete_contact
from openemail.core.model import Profile
from openemail.shared import PREFIX, notifier, run_task
from openemail.store import address_book, broadcasts, inbox, profile_categories


@Gtk.Template(resource_path=f"{PREFIX}/gtk/profile-view.ui")
class MailProfileView(Adw.Bin):
    """A page presenting a user's profile."""

    __gtype_name__ = "MailProfileView"

    _groups: list[Adw.PreferencesGroup]

    page: Adw.PreferencesPage = Gtk.Template.Child()

    confirm_remove_dialog: Adw.Dialog = Gtk.Template.Child()

    name = GObject.Property(type=str)
    address = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)
    away = GObject.Property(type=bool, default=False)
    can_remove = GObject.Property(type=bool, default=False)

    visible_child_name = GObject.Property(type=str, default="empty")

    _profile: Profile | None = None

    @property
    def profile(self) -> Profile | None:
        """Profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None) -> None:
        self._profile = profile

        if not profile:
            self.visible_child_name = "not-found"
            self.can_remove = False
            return

        string = str(profile.address)
        if any(contact.address == string for contact in address_book):  # type: ignore
            self.can_remove = True
        else:
            self.can_remove = False

        self.name = str(profile.required["name"])
        self.address = profile.address
        self.away = away.value if (away := profile.optional.get("away")) else False

        while self._groups:
            self.page.remove(self._groups.pop())

        self._groups = []

        for category, fields in profile_categories.items():
            group = None
            for ident, name in fields.items():
                if not (profile_field := profile.optional.get(ident)):
                    continue

                if not group:
                    self._groups.append(
                        group := Adw.PreferencesGroup(
                            title=category.name,
                            separate_rows=True,  # type: ignore
                        )
                    )
                    self.page.add(group)

                row = Adw.ActionRow(
                    title=name,
                    subtitle=str(profile_field),
                    subtitle_selectable=True,
                )
                row.add_css_class("property")
                row.add_prefix(
                    Gtk.Image(
                        valign=Gtk.Align.START,
                        icon_name=f"{ident}-symbolic",
                        margin_top=18,
                    )
                )
                group.add(row)

        self.visible_child_name = "profile"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._groups = []

        self.add_controller(
            controller := Gtk.ShortcutController(
                scope=Gtk.ShortcutScope.GLOBAL,
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("Delete|KP_Delete"),
                Gtk.CallbackAction.new(
                    lambda *_: not (self._remove_contact() if self.can_remove else None)
                ),
            )
        )

    @Gtk.Template.Callback()
    def _remove_contact(self, *_args: Any) -> None:
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_remove(self, _obj: Any, response: str) -> None:
        if response != "remove":
            return

        if not self.profile:
            return

        address = self.profile.address

        def removal_failed() -> None:
            notifier.send(_("Failed to remove contact"))
            address_book.add(address)
            run_task(broadcasts.update())
            run_task(inbox.update())

        run_task(delete_contact(address), on_failure=removal_failed)

        address_book.remove(self.profile.address)
        run_task(broadcasts.update())
        run_task(inbox.update())
