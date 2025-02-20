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

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from openemail import shared
from openemail.network import fetch_profile, fetch_profile_image
from openemail.user import Address, Profile


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/profile-page.ui")
class MailProfilePage(Adw.Bin):
    """A page presenting a user's profile."""

    __gtype_name__ = "MailProfilePage"

    stack: Gtk.Stack = Gtk.Template.Child()
    not_found_page: Adw.StatusPage = Gtk.Template.Child()
    page: Adw.PreferencesPage = Gtk.Template.Child()

    _profile: Profile | None = None
    _name: str | None = None
    _paintable: Gdk.Paintable | None = None

    _groups: list[Adw.PreferencesGroup] = []

    @property
    def profile(self) -> Profile | None:
        """Profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None) -> None:
        self._profile = profile

        if not profile:
            self.stack.set_visible_child(self.not_found_page)
            return

        self.name = str(profile.required["name"])

        for group in self._groups:
            self.page.remove(group)

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
                    self._groups.append(
                        group := Adw.PreferencesGroup(
                            title=name,
                            separate_rows=True,  # type: ignore
                        )
                    )
                    self.page.add(group)

                row = Adw.ActionRow(
                    title=field.name,
                    subtitle=str(field),
                    subtitle_selectable=True,
                )
                row.add_css_class("property")
                row.add_prefix(Gtk.Image.new_from_icon_name(f"{key}-symbolic"))
                group.add(row)

        self.stack.set_visible_child(self.page)

    @GObject.Property(type=str)
    def name(self) -> str | None:
        """Get the user's name."""
        return self._name

    @name.setter
    def name(self, name: str) -> None:
        self._name = name

    @GObject.Property(type=Gdk.Paintable)
    def paintable(self) -> Gdk.Paintable | None:
        """Get the `Gdk.Paintable` of the user's profile image."""
        return self._paintable

    @paintable.setter
    def paintable(self, paintable: Gdk.Paintable | None) -> None:
        self._paintable = paintable
