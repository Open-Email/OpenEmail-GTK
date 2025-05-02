# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gdk, GObject, Gtk

from openemail import PREFIX, mail, run_task
from openemail.mail import CoreProfile


@Gtk.Template(resource_path=f"{PREFIX}/gtk/profile-view.ui")
class ProfileView(Adw.Bin):
    """A page presenting a user's profile."""

    __gtype_name__ = "ProfileView"

    _groups: list[Adw.PreferencesGroup]

    page: Adw.PreferencesPage = Gtk.Template.Child()

    confirm_remove_dialog: Adw.Dialog = Gtk.Template.Child()

    name = GObject.Property(type=str)
    address = GObject.Property(type=str)
    profile_image = GObject.Property(type=Gdk.Paintable)
    away = GObject.Property(type=bool, default=False)
    can_remove = GObject.Property(type=bool, default=False)

    visible_child_name = GObject.Property(type=str, default="empty")

    _profile: CoreProfile | None = None

    @property
    def profile(self) -> CoreProfile | None:
        """Profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: CoreProfile | None) -> None:
        self._profile = profile

        if not profile:
            self.visible_child_name = "not-found"
            self.can_remove = False
            return

        string = str(profile.address)
        if any(contact.address == string for contact in mail.address_book):  # type: ignore
            self.can_remove = True
        else:
            self.can_remove = False

        self.name = profile.name
        self.address = profile.address
        self.away = profile.away

        while self._groups:
            self.page.remove(self._groups.pop())

        self._groups = []

        for category, fields in mail.profile_categories.items():
            group = None
            for ident, name in fields.items():
                if not (profile_field := getattr(profile, ident.replace("-", "_"))):
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
                    use_markup=False,
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

    @Gtk.Template.Callback()
    def _remove_contact(self, *_args: Any) -> None:
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_remove(self, _obj: Any, response: str) -> None:
        if (response != "remove") or (not self.profile):
            return

        run_task(mail.address_book.delete(self.profile.address))
