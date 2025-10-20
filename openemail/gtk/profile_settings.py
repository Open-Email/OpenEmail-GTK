# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, cast

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from openemail import PREFIX, Property, profile, tasks
from openemail.core import client
from openemail.core.model import WriteError
from openemail.profile import Profile, ProfileField

from .form import Form

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/profile-settings.ui")
class ProfileSettings(Adw.PreferencesDialog):
    """A page presenting the user's editable public profile."""

    __gtype_name__ = __qualname__

    name: Adw.EntryRow = child
    away: Adw.ExpanderRow = child
    away_warning: Adw.EntryRow = child
    status: Adw.EntryRow = child
    about: Adw.EntryRow = child
    name_form: Form = child

    address = Property(str)

    pending = Property(bool)
    visible_child_name = Property(str, default="loading")

    _pages: list[Adw.PreferencesPage]
    _fields: dict[str, Callable[[], str]]
    _changed: bool = False

    _profile: Profile | None = None

    @Property(Profile)
    def profile(self) -> Profile | None:
        """The profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None):
        self._profile = profile

        while self._pages:
            self.remove(self._pages.pop())

        if not profile:
            self.visible_child_name = "loading"
            self._changed = False
            return

        self.address = profile.value_of("address") or ""
        self.name.props.text = profile.value_of("name")
        self.away.props.enable_expansion = profile.value_of("away")
        self.away.props.expanded = self.away.props.enable_expansion
        self.away_warning.props.text = profile.value_of("away-warning") or ""
        self.status.props.text = profile.value_of("status") or ""
        self.about.props.text = profile.value_of("about") or ""

        for category in Profile.categories:
            if category.ident == "general":  # Already added manually
                continue

            page = Adw.PreferencesPage(
                title=category.name,
                icon_name=f"{category.ident}-symbolic",
            )

            group = Adw.PreferencesGroup()
            group.bind_model(category, self._create_row, profile)  # pyright: ignore[reportAttributeAccessIssue]
            page.add(group)

            self._pages.append(page)
            self.add(page)

        self.visible_child_name = "profile"
        self._changed = False

    def _create_row(self, field: ProfileField, profile: Profile) -> Gtk.Widget:
        value = profile.value_of(field.ident)

        if isinstance(value, bool):
            row = Adw.SwitchRow(active=value)
            row.connect("notify::active", self._on_change)
            self._fields[field.ident] = lambda r=row: "Yes" if r.props.active else "No"
        else:
            row = Adw.EntryRow(text=str(value or ""))
            row.add_css_class("property")
            row.connect("changed", self._on_change)
            self._fields[field.ident] = row.get_text

        row.props.title = field.name
        row.add_prefix(Gtk.Image.new_from_icon_name(f"{field.ident}-symbolic"))

        return row

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._pages = []
        self._fields = {
            "name": self.name.get_text,
            "away": lambda: "Yes" if self.away.props.enable_expansion else "No",
            "away-warning": self.away_warning.get_text,
            "status": self.status.get_text,
            "about": self.about.get_text,
        }

        Profile.of(client.user).connect(
            "notify::updating",
            lambda p, _: self.set_property("profile", None if p.updating else p),
        )

    @Gtk.Template.Callback()
    def _is_image(self, _obj, image: Gdk.Paintable | None) -> bool:
        return bool(image)

    @Gtk.Template.Callback()
    def _delete_image(self, *_args):
        self.pending = True
        tasks.create(
            profile.delete_image(),
            lambda _: self.set_property("pending", False),
        )

    @Gtk.Template.Callback()
    def _on_change(self, *_args):
        self._changed = True

    @Gtk.Template.Callback()
    def _closed(self, *_args):
        if not (self._changed and self.name_form.valid):
            return

        if not self.away.props.enable_expansion:
            self.away_warning.props.text = ""

        self._changed = False
        tasks.create(profile.update({key: f() for key, f in self._fields.items()}))

    @tasks.callback
    async def _replace_image(self, *_args):
        try:
            file = await cast(
                "Awaitable[Gio.File]",
                Gtk.FileDialog(
                    initial_name=_("Select an Image"),
                    default_filter=Gtk.FileFilter(
                        name=_("Images"),
                        mime_types=tuple(
                            mime_type
                            for pixbuf_format in GdkPixbuf.Pixbuf.get_formats()
                            for mime_type in (pixbuf_format.get_mime_types() or ())
                        ),
                    ),
                ).open(win if isinstance(win := self.props.root, Gtk.Window) else None),
            )
        except GLib.Error:
            return

        if not (file and (path := file.get_path())):
            return

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error:
            return

        if not pixbuf:
            return

        self.pending = True

        with suppress(WriteError):
            await profile.update_image(pixbuf)

        self.pending = False
