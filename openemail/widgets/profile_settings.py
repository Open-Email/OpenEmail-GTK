# profile_settings.py
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


from typing import Any, Callable

from gi.repository import Adw, Gdk, GObject, Gtk

from openemail import shared
from openemail.core.network import delete_profile_image, update_profile
from openemail.core.user import Profile
from openemail.widgets.form import MailForm


@Gtk.Template(resource_path=f"{shared.PREFIX}/gtk/profile-settings.ui")
class MailProfileSettings(Adw.PreferencesDialog):
    """A page presenting the local user's editable public profile."""

    __gtype_name__ = "MailProfileSettings"

    name: Adw.EntryRow = Gtk.Template.Child()
    away: Adw.SwitchRow = Gtk.Template.Child()
    status: Adw.EntryRow = Gtk.Template.Child()
    about: Adw.EntryRow = Gtk.Template.Child()
    name_form: MailForm = Gtk.Template.Child()

    _pages: list[Adw.PreferencesPage]
    _fields: dict[str, Callable[[], str]]

    address = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    can_delete = GObject.Property(type=bool, default=True)
    visible_child_name = GObject.Property(type=str, default="loading")

    _profile: Profile | None = None

    @property
    def profile(self) -> Profile | None:
        """Profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None) -> None:
        self._profile = profile

        if not profile:
            self.visible_child_name = "loading"
            return

        self.name.set_text(str(profile.required["name"]))
        self.status.set_text(str(profile.optional.get("status") or ""))
        self.about.set_text(str(profile.optional.get("about") or ""))

        self.address = profile.address
        self.away.set_active(
            away.value if (away := profile.optional.get("away")) else False
        )

        while self._pages:
            self.remove(self._pages.pop())

        for category, fields in shared.profile_categories.items():
            if category.ident == "general":  # Already added manually
                continue

            self._pages.append(
                page := Adw.PreferencesPage(
                    title=category.name,
                    icon_name=f"{category.ident}-symbolic",
                )
            )
            self.add(page)
            page.add(outer := Adw.PreferencesGroup())
            outer.add(stack := Gtk.Stack(vexpand=True))
            stack.add_named(Adw.Spinner(), "loading")  # type: ignore
            stack.add_named(
                inner := Adw.PreferencesGroup(
                    separate_rows=True,  # type: ignore
                ),
                "profile",
            )

            for ident, name in fields.items():
                profile_field = profile.optional.get(ident)

                row = Adw.EntryRow(
                    title=name,
                    text=str(profile_field or ""),
                )
                row.add_css_class("property")
                row.add_prefix(
                    Gtk.Image(
                        valign=Gtk.Align.START,
                        icon_name=f"{ident}-symbolic",
                        margin_top=18,
                    )
                )
                inner.add(row)
                self._fields[ident] = row.get_text

            self.bind_property("visible-child-name", stack, "visible-child-name")

        self.visible_child_name = "profile"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pages = []
        self._fields = {
            "name": self.name.get_text,
            "away": lambda: "Yes" if self.away.get_active() else "No",
            "status": self.status.get_text,
            "about": self.about.get_text,
        }

    @Gtk.Template.Callback()
    def _is_image(self, _obj: Any, image: Gdk.Paintable | None) -> bool:
        return bool(image)

    @Gtk.Template.Callback()
    def _delete_image(self, *_args: Any) -> None:
        if not shared.user:
            return

        self.can_delete = False
        shared.run_task(
            delete_profile_image(shared.user),
            lambda: shared.run_task(
                shared.update_user_profile(),
                self.set_property("can-delete", True),
            ),
        )

    @Gtk.Template.Callback()
    def _closed(self, *_args: Any) -> None:
        if (not shared.user) or self.name_form.invalid:
            return

        shared.run_task(
            update_profile(
                shared.user,
                {key: f() for key, f in self._fields.items()},
            ),
            lambda: shared.run_task(shared.update_user_profile()),
        )
