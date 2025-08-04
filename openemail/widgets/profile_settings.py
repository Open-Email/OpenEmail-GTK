# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, cast

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from openemail import PREFIX, create_task
from openemail.app import mail
from openemail.app.mail import Profile, ProfileField, WriteError

from .form import Form


@Gtk.Template.from_resource(f"{PREFIX}/profile-settings.ui")
class ProfileSettings(Adw.PreferencesDialog):
    """A page presenting the user's editable public profile."""

    __gtype_name__ = "ProfileSettings"

    name: Adw.EntryRow = Gtk.Template.Child()
    away: Adw.ExpanderRow = Gtk.Template.Child()
    away_warning: Adw.EntryRow = Gtk.Template.Child()
    status: Adw.EntryRow = Gtk.Template.Child()
    about: Adw.EntryRow = Gtk.Template.Child()
    name_form: Form = Gtk.Template.Child()

    address = GObject.Property(type=str)

    pending = GObject.Property(type=bool, default=False)
    visible_child_name = GObject.Property(type=str, default="loading")

    _pages: list[Adw.PreferencesPage]
    _fields: dict[str, Callable[[], str]]
    _changed: bool = False

    _profile: Profile | None = None

    @GObject.Property(type=Profile)
    def profile(self) -> Profile | None:
        """Get the profile of the user, if one was found."""
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

        self.address = str(profile.value_of("address") or "")
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
                title=category.name, icon_name=f"{category.ident}-symbolic"
            )
            self._pages.append(page)
            self.add(page)

            group = Adw.PreferencesGroup()
            group.bind_model(category, self._create_row, profile)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            page.add(group)

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

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._pages = []
        self._fields = {
            "name": self.name.get_text,
            "away": lambda: "Yes" if self.away.props.enable_expansion else "No",
            "away-warning": self.away_warning.get_text,
            "status": self.status.get_text,
            "about": self.about.get_text,
        }

        mail.user_profile.connect(
            "notify::updating",
            lambda p, _: self.set_property("profile", None if p.updating else p),  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        )

    @Gtk.Template.Callback()
    def _is_image(self, _obj: Any, image: Gdk.Paintable | None) -> bool:
        return bool(image)

    @Gtk.Template.Callback()
    def _delete_image(self, *_args: Any) -> None:
        self.pending = True
        create_task(
            mail.delete_profile_image(),
            lambda _: self.set_property("pending", False),
        )

    @Gtk.Template.Callback()
    def _replace_image(self, *_args: Any) -> None:
        create_task(self._replace_image_task())

    @Gtk.Template.Callback()
    def _on_change(self, *_args: Any) -> None:
        self._changed = True

    @Gtk.Template.Callback()
    def _closed(self, *_args: Any) -> None:
        if not (self._changed and self.name_form.valid):
            return

        if not self.away.props.enable_expansion:
            self.away_warning.props.text = ""

        self._changed = False
        create_task(mail.update_profile({key: f() for key, f in self._fields.items()}))

    async def _replace_image_task(self) -> None:
        try:
            gfile = await cast(
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

        if not (gfile and (path := gfile.get_path())):
            return

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error:
            return

        if not pixbuf:
            return

        self.pending = True

        with suppress(WriteError):
            await mail.update_profile_image(pixbuf)

        self.pending = False
