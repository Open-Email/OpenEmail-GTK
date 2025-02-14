# profile_page.py
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

from gi.repository import Adw, GLib, Gtk

from openemail import shared
from openemail.client import Address, Profile, fetch_profile


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/profile-page.ui")
class MailProfilePage(Adw.Bin):
    __gtype_name__ = "MailProfilePage"

    stack: Gtk.Stack = Gtk.Template.Child()
    not_selected_page: Adw.StatusPage = Gtk.Template.Child()
    not_found_page: Adw.StatusPage = Gtk.Template.Child()
    spinner: Adw.Spinner = Gtk.Template.Child()  # type: ignore
    page: Adw.Bin = Gtk.Template.Child()

    _address: Address | None = None

    @property
    def address(self) -> Address | None:
        return self._address

    @address.setter
    def address(self, address: Address) -> None:
        if address == self._address:
            return

        self._address = address

        self.stack.set_visible_child(self.spinner)

        def thread_func() -> None:
            GLib.idle_add(self.__update_profile, fetch_profile(address))

        GLib.Thread.new(None, thread_func)

    def __init__(self, address: Address | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not address:
            self.stack.set_visible_child(self.not_selected_page)
            return

        self.address = address

    def __update_profile(self, profile: Profile | None) -> None:
        if not profile:
            self.stack.set_visible_child(self.not_found_page)
            return

        self.page.set_child(page := Adw.PreferencesPage())
        self.stack.set_visible_child(self.page)

        name = profile.required["name"].value

        page.add(avatar_group := Adw.PreferencesGroup())
        avatar_group.add(Adw.Avatar.new(128, name, True))

        page.add(title_group := Adw.PreferencesGroup())
        title_group.add(title_label := Gtk.Label(label=name))
        title_label.add_css_class("title-1")

        for name, category in {
            _("General"): (
                "away",
                "status",
                "about",
            ),
            _("Personal"): (
                "gender",
                "relationship-status",
                "birthday",
                "education",
                "languages",
                "places-lived",
                "notes",
            ),
            _("Work"): (
                "work",
                "organization",
                "department",
                "job-title",
            ),
            _("Interests"): (
                "interests",
                "books",
                "movies",
                "music",
                "sports",
            ),
            _("Contacts"): (
                "website",
                "location",
                "mailing-address",
                "phone",
            ),
        }.items():
            group = None
            for key in category:
                if not ((field := profile.optional.get(key)) and field.name):
                    continue

                if not group:
                    page.add(
                        group := Adw.PreferencesGroup(
                            title=name,
                            separate_rows=True,  # type: ignore
                        )
                    )

                row = Adw.ActionRow(
                    title=field.name,
                    subtitle=field.string,
                    subtitle_selectable=True,
                )
                row.add_css_class("property")
                row.add_prefix(Gtk.Image.new_from_icon_name(f"{key}-symbolic"))
                group.add(row)
