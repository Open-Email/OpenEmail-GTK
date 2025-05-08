# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail import APP_ID, PREFIX, mail, run_task
from openemail.core.model import Address
from openemail.mail import Profile


@Gtk.Template(resource_path=f"{PREFIX}/gtk/profile-view.ui")
class ProfileView(Adw.Bin):
    """A page presenting a user's profile."""

    __gtype_name__ = "ProfileView"

    _groups: list[Adw.PreferencesGroup]

    page: Adw.PreferencesPage = Gtk.Template.Child()

    image_dialog: Adw.Dialog = Gtk.Template.Child()
    confirm_remove_dialog: Adw.AlertDialog = Gtk.Template.Child()

    name = GObject.Property(type=str)
    address = GObject.Property(type=str)
    away = GObject.Property(type=bool, default=False)
    can_remove = GObject.Property(type=bool, default=False)
    app_icon_name = GObject.Property(type=str, default=f"{APP_ID}-symbolic")

    visible_child_name = GObject.Property(type=str, default="empty")

    _profile: Profile | None = None

    @GObject.Property(type=Profile)
    def profile(self) -> Profile | None:
        """Profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None) -> None:
        self._profile = profile

        if not profile:
            self.visible_child_name = "empty"
            self.can_remove = False
            return

        self.can_remove = profile in mail.address_book if profile.address else False

        if not profile.value_of("address"):
            self.visible_child_name = "not-found"
            return

        self.name = profile.value_of("name")
        self.address = str(profile.value_of("address") or "")
        self.away = profile.value_of("away") or False

        while self._groups:
            self.page.remove(self._groups.pop())

        self._groups = []

        for category, fields in Profile.categories.items():
            group = None
            for ident, name in fields.items():
                if not (value := str(profile.value_of(ident) or "")):
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
                    subtitle=value,
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
        if (response != "remove") or (not self._profile):
            return

        try:
            run_task(mail.address_book.delete(Address(self._profile.address)))
        except ValueError:
            return

    @Gtk.Template.Callback()
    def _show_image_dialog(self, *_args: Any) -> None:
        if not self.profile.image:
            return

        self.image_dialog.present(self)
