# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from collections.abc import Awaitable, Callable
from typing import Any, cast

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from openemail import PREFIX, mail, run_task
from openemail.mail import Profile, WriteError

from .form import MailForm


@Gtk.Template(resource_path=f"{PREFIX}/gtk/profile-settings.ui")
class ProfileSettings(Adw.PreferencesDialog):
    """A page presenting the user's editable public profile."""

    __gtype_name__ = "ProfileSettings"

    name: Adw.EntryRow = Gtk.Template.Child()
    away: Adw.ExpanderRow = Gtk.Template.Child()
    away_warning: Adw.EntryRow = Gtk.Template.Child()
    status: Adw.EntryRow = Gtk.Template.Child()
    about: Gtk.TextBuffer = Gtk.Template.Child()
    name_form: MailForm = Gtk.Template.Child()

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

        for category, fields in Profile.categories.items():
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
                if ident == "notes":
                    buffer = Gtk.TextBuffer(text=str(profile.value_of(ident) or ""))
                    buffer.connect("changed", self._on_change)

                    text_view = Gtk.TextView(
                        buffer=buffer,
                        hexpand=True,
                        top_margin=12,
                        bottom_margin=12,
                        left_margin=12,
                        right_margin=12,
                        wrap_mode=Gtk.WrapMode.WORD_CHAR,
                    )
                    text_view.add_css_class("inline")

                    box = Gtk.Box()
                    box.append(text_view)
                    box.add_css_class("card")

                    group = Adw.PreferencesGroup(title=name)
                    group.add(box)

                    page.add(group)
                    self._fields[ident] = lambda: buffer.get_property("text")
                    continue

                row = Adw.EntryRow(title=name, text=str(profile.value_of(ident) or ""))
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
            "about": lambda: self.about.get_property("text"),
        }

        mail.user_profile.connect(
            "notify::updating",
            lambda p, _: self.set_property("profile", None if p.updating else p),
        )

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

        if not self.away.props.enable_expansion:
            self.away_warning.props.text = ""

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
            gfile = await cast(
                Awaitable[Gio.File],
                Gtk.FileDialog(initial_name=_("Select an Image"), filters=filters).open(
                    win if isinstance(win := self.props.root, Gtk.Window) else None
                ),
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

        try:
            await mail.update_profile_image(pixbuf)
        except WriteError:
            pass

        self.pending = False
