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

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from openemail import PREFIX, mail, run_task
from openemail.mail import Profile, WriteError

from .form import MailForm


@Gtk.Template(resource_path=f"{PREFIX}/gtk/profile-settings.ui")
class MailProfileSettings(Adw.PreferencesDialog):
    """A page presenting the user's editable public profile."""

    __gtype_name__ = "MailProfileSettings"

    name: Adw.EntryRow = Gtk.Template.Child()
    away: Adw.ExpanderRow = Gtk.Template.Child()
    away_warning: Adw.EntryRow = Gtk.Template.Child()
    status: Adw.EntryRow = Gtk.Template.Child()
    about: Adw.EntryRow = Gtk.Template.Child()
    name_form: MailForm = Gtk.Template.Child()

    _pages: list[Adw.PreferencesPage]
    _fields: dict[str, Callable[[], str]]
    _changed: bool = False

    address = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)

    pending = GObject.Property(type=bool, default=False)
    visible_child_name = GObject.Property(type=str, default="loading")

    _profile: Profile | None = None

    @property
    def profile(self) -> Profile | None:
        """Profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None) -> None:
        self._profile = profile

        while self._pages:
            self.remove(self._pages.pop())

        if not profile:
            self.visible_child_name = "loading"
            self._changed = False
            return

        self.address = profile.address
        self.name.set_text(profile.name)
        self.away.props.enable_expansion = self.away.props.expanded = profile.away
        self.away_warning.set_text(profile.away_warning or "")
        self.status.set_text(profile.status or "")
        self.about.set_text(profile.about or "")

        for category, fields in mail.profile_categories.items():
            if category.ident == "general":  # Already added manually
                continue

            self._pages.append(
                page := Adw.PreferencesPage(
                    title=category.name,
                    icon_name=f"{category.ident}-symbolic",
                )
            )
            self.add(page)
            page.add(group := Adw.PreferencesGroup())

            for ident, name in fields.items():
                profile_field = getattr(profile, ident.replace("-", "_"))

                row = Adw.EntryRow(
                    title=name,
                    text=str(profile_field or ""),
                )
                row.add_css_class("property")
                row.add_prefix(Gtk.Image(icon_name=f"{ident}-symbolic"))
                row.connect("changed", self._on_change)
                group.add(row)
                self._fields[ident] = row.get_text

        self.visible_child_name = "profile"
        self._changed = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pages = []
        self._fields = {
            "name": self.name.get_text,
            "away": lambda: "Yes" if self.away.get_enable_expansion() else "No",
            "away-warning": self.away_warning.get_text,
            "status": self.status.get_text,
            "about": self.about.get_text,
        }

    @Gtk.Template.Callback()
    def _is_image(self, _obj: Any, image: Gdk.Paintable | None) -> bool:
        return bool(image)

    @Gtk.Template.Callback()
    def _delete_image(self, *_args: Any) -> None:
        self.pending = True
        run_task(
            mail.delete_profile_image(),
            lambda _: self.set_property("pending", False),
        )

    @Gtk.Template.Callback()
    def _replace_image(self, *_args: Any) -> None:
        run_task(self._replace_image_task())

    @Gtk.Template.Callback()
    def _on_change(self, *_args: Any) -> None:
        self._changed = True

    @Gtk.Template.Callback()
    def _closed(self, *_args: Any) -> None:
        if (not self._changed) or self.name_form.invalid:
            return

        if not self.away.get_enable_expansion():
            self.away_warning.set_text("")

        self._changed = False
        run_task(mail.update_profile({key: f() for key, f in self._fields.items()}))

    async def _replace_image_task(self) -> None:
        (filters := Gio.ListStore.new(Gtk.FileFilter)).append(
            Gtk.FileFilter(
                name=_("Images"),
                mime_types=tuple(
                    mime_type
                    for pixbuf_format in GdkPixbuf.Pixbuf.get_formats()
                    for mime_type in (pixbuf_format.get_mime_types() or ())
                ),
            )
        )

        try:
            if not (
                (
                    gfile := await Gtk.FileDialog(  # type: ignore
                        initial_name=_("Select an Image"), filters=filters
                    ).open(
                        win if isinstance(win := self.get_root(), Gtk.Window) else None
                    )
                )
                and (path := gfile.get_path())
            ):
                return
        except GLib.Error:
            return

        try:
            if not (pixbuf := GdkPixbuf.Pixbuf.new_from_file(path)):
                return
        except GLib.Error:
            return

        self.pending = True

        try:
            await mail.update_profile_image(pixbuf)
        except WriteError:
            pass

        self.pending = False
