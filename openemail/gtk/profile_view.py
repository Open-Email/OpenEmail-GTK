# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, GObject, Gtk

import openemail as app
from openemail import APP_ID, PREFIX, Address, Profile, ProfileField, Property

child = Gtk.Template.Child()


@Gtk.Template.from_resource(f"{PREFIX}/profile-view.ui")
class ProfileView(Adw.Bin):
    """A page presenting a user's profile."""

    __gtype_name__ = "ProfileView"

    _groups: list[Adw.PreferencesGroup]

    page: Adw.PreferencesPage = child

    image_dialog: Adw.Dialog = child
    confirm_remove_dialog: Adw.AlertDialog = child

    name = Property(str)
    address = Property(str)
    away = Property(bool)
    is_contact = Property(bool)
    app_icon_name = Property(str, default=f"{APP_ID}-symbolic")
    broadcasts = Property(bool)

    visible_child_name = Property(str, default="empty")

    _profile: Profile | None = None
    _broadcasts_binding: GObject.Binding | None = None

    @Property(Profile)
    def profile(self) -> Profile | None:
        """The profile of the user, if one was found."""
        return self._profile

    @profile.setter
    def profile(self, profile: Profile | None):
        self._profile = profile

        if not profile:
            self.visible_child_name = "empty"
            return

        self.is_contact = profile in app.address_book if profile.address else False

        if not profile.value_of("address"):
            self.visible_child_name = "not-found"
            return

        self.name = profile.value_of("name")
        self.address = profile.value_of("address") or ""
        self.away = profile.value_of("away") or False

        while self._groups:
            self.page.remove(self._groups.pop())

        self._groups = []

        def _filter_empty_fields(field: ProfileField) -> bool:
            return bool(profile.value_of(field.ident))

        empty_fields_filter = Gtk.CustomFilter.new(_filter_empty_fields)
        for category in Profile.categories:
            if category.ident == "configuration":  # Only relevant for settings
                continue

            if not (filtered := Gtk.FilterListModel.new(category, empty_fields_filter)):
                continue

            group = Adw.PreferencesGroup(title=category.name, separate_rows=True)
            group.bind_model(filtered, self._create_row, profile)  # pyright: ignore[reportAttributeAccessIssue]
            self._groups.append(group)
            self.page.add(group)

        if self._broadcasts_binding:
            self._broadcasts_binding.unbind()

        self._broadcasts_binding = Property.bind(
            profile, "receive-broadcasts", self, "broadcasts", bidirectional=True
        )

        self.visible_child_name = "profile"

    @staticmethod
    def _create_row(field: ProfileField, profile: Profile) -> Gtk.Widget:
        row = Adw.ActionRow(
            title=field.name,
            subtitle=profile.value_of(field.ident),
            subtitle_selectable=True,
            use_markup=False,
        )
        row.add_css_class("property")
        row.add_prefix(
            Gtk.Image(
                valign=Gtk.Align.START,
                icon_name=f"{field.ident}-symbolic",
                margin_top=18,
            )
        )
        return row

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._groups = []

    @Gtk.Template.Callback()
    def _remove_contact(self, *_args):
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_remove(self, *_args):
        if not self.profile:
            return

        try:
            app.create_task(app.address_book.delete(Address(self.profile.address)))
        except ValueError:
            return

    @Gtk.Template.Callback()
    def _show_image_dialog(self, *_args):
        if not self.profile.image:
            return

        self.image_dialog.present(self)
