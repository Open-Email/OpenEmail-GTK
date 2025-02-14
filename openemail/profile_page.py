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

from gi.repository import Adw, Gtk

from openemail.client import Profile


class MailProfilePage(Adw.Bin):
    __gtype_name__ = "MailProfilePage"

    def __init__(self, profile: Profile | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_profile(profile)

    def set_profile(self, profile: Profile | None) -> None:
        if not profile:
            self.set_child(
                Adw.StatusPage(
                    title=_("No Profile Information"),
                    icon_name="about-symbolic",
                )
            )
            return

        self.set_child(page := Adw.PreferencesPage())

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
                    page.add(group := Adw.PreferencesGroup(title=name))

                row = Adw.ActionRow(
                    title=field.name,
                    subtitle=field.string,
                    subtitle_selectable=True,
                )
                row.add_css_class("property")
                row.add_prefix(Gtk.Image.new_from_icon_name(f"{key}-symbolic"))
                group.add(row)
