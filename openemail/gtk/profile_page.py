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
    not_selected_page: Adw.StatusPage = Gtk.Template.Child()
    not_found_page: Adw.StatusPage = Gtk.Template.Child()
    spinner: Adw.Spinner = Gtk.Template.Child()  # type: ignore
    page: Adw.Bin = Gtk.Template.Child()

    _address: Address | None = None

    @property
    def address(self) -> Address | None:
        """The Mail/HTTPS address of the user."""
        return self._address

    @address.setter
    def address(self, address: Address) -> None:
        if address == self._address:
            return

        self._address = address

        self.stack.set_visible_child(self.spinner)

        def update_profile() -> None:
            GLib.idle_add(self.__update_profile, fetch_profile(address), address)

        def update_image() -> None:
            GLib.idle_add(self.__update_image, fetch_profile_image(address), address)

        GLib.Thread.new(None, update_profile)
        GLib.Thread.new(None, update_image)

    _avatar_binding: GObject.Binding | None = None
    _paintable: Gdk.Paintable | None = None

    @GObject.Property(type=Gdk.Paintable)
    def paintable(self) -> Gdk.Paintable | None:
        """Get the `Gdk.Paintable` of the user's profile picture."""
        return self._paintable

    @paintable.setter
    def paintable(self, paintable: Gdk.Paintable) -> None:
        self._paintable = paintable

    def __init__(self, address: Address | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not address:
            self.stack.set_visible_child(self.not_selected_page)
            return

        self.address = address

    def __update_profile(self, profile: Profile | None, address: Address) -> None:
        if address != self.address:
            return

        if self._avatar_binding:
            self._avatar_binding.unbind()

        if not profile:
            self.stack.set_visible_child(self.not_found_page)
            return

        self.page.set_child(page := Adw.PreferencesPage())
        self.stack.set_visible_child(self.page)

        name = profile.required["name"].value

        page.add(avatar_group := Adw.PreferencesGroup())

        avatar_group.add(avatar := Adw.Avatar.new(128, name, True))
        self._avatar_binding = self.bind_property(
            "paintable",
            avatar,
            "custom-image",
            GObject.BindingFlags.SYNC_CREATE,
        )

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
                    subtitle=str(field),
                    subtitle_selectable=True,
                )
                row.add_css_class("property")
                row.add_prefix(Gtk.Image.new_from_icon_name(f"{key}-symbolic"))
                group.add(row)

    def __update_image(self, image: bytes, address: Address) -> None:
        if address != self.address:
            return

        try:
            self.paintable = Gdk.Texture.new_from_bytes(
                GLib.Bytes.new(image)  # type: ignore
            )
        except GLib.Error:
            pass
