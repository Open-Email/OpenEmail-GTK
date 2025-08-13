# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from contextlib import suppress
from typing import Any

from gi.repository import Adw, GObject, Gtk

import openemail as app
from openemail import PREFIX, settings

from .form import Form
from .window import Window


@Gtk.Template.from_resource(f"{PREFIX}/preferences.ui")
class Preferences(Adw.PreferencesDialog):
    """The application's preferences dialog."""

    __gtype_name__ = "Preferences"

    confirm_remove_dialog: Adw.AlertDialog = Gtk.Template.Child()
    confirm_delete_dialog: Adw.AlertDialog = Gtk.Template.Child()
    sync_interval_combo_row: Adw.ComboRow = Gtk.Template.Child()
    empty_trash_combo_row: Adw.ComboRow = Gtk.Template.Child()

    domains: Adw.PreferencesGroup = Gtk.Template.Child()
    add_domain_dialog: Adw.AlertDialog = Gtk.Template.Child()
    domain_entry: Adw.EntryRow = Gtk.Template.Child()
    domain_form: Form = Gtk.Template.Child()

    private_signing_key = GObject.Property(type=str)
    private_encryption_key = GObject.Property(type=str)
    public_signing_key = GObject.Property(type=str)
    public_encryption_key = GObject.Property(type=str)

    _sync_intervals = (0, 60, 300, 900, 1800, 3600)
    _trash_intervals = (0, 1, 7, 14, 30)
    _domain_rows: list[Adw.PreferencesRow]

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._domain_rows = []
        settings.connect("changed::trusted-domains", self._build_domains)
        self._build_domains()

        self.private_signing_key = str(app.user.signing_keys)
        self.private_encryption_key = str(app.user.encryption_keys.private)
        self.public_signing_key = str(app.user.signing_keys.public)
        self.public_encryption_key = str(app.user.encryption_keys.public)

        with suppress(ValueError):
            self.sync_interval_combo_row.props.selected = self._sync_intervals.index(
                settings.get_uint("sync-interval")
            )
            self.empty_trash_combo_row.props.selected = self._trash_intervals.index(
                settings.get_uint("empty-trash-interval")
            )

    @Gtk.Template.Callback()
    def _sync_interval_selected(self, row: Adw.ComboRow, *_args):
        settings.set_uint(
            "sync-interval",
            self._sync_intervals[row.props.selected],
        )

    @Gtk.Template.Callback()
    def _trash_interval_selected(self, row: Adw.ComboRow, *_args):
        settings.set_uint(
            "empty-trash-interval",
            self._trash_intervals[row.props.selected],
        )

    @Gtk.Template.Callback()
    def _remove_account(self, *_args):
        self.confirm_remove_dialog.present(self)

    @Gtk.Template.Callback()
    def _delete_account(self, *_args):
        self.confirm_delete_dialog.present(self)

    @Gtk.Template.Callback()
    def _confirm_delete(self, *_args):
        self.force_close()
        app.create_task(app.delete_account())

    @Gtk.Template.Callback()
    def _confirm_remove(self, *_args):
        self.force_close()
        app.log_out()

        if not isinstance(win := self.props.root, Window):
            return

        win.visible_child_name = "auth"

    @Gtk.Template.Callback()
    def _new_domain(self, *_args):
        self.domain_form.reset()
        self.add_domain_dialog.present(self)

    @Gtk.Template.Callback()
    def _add_domain(self, *_args):
        if (domain := self.domain_entry.props.text) in (
            current := settings.get_strv("trusted-domains")
        ):
            return

        settings.set_strv("trusted-domains", (domain, *current))
        self._build_domains()

    def _remove_domain(self, domain: str):
        try:
            (current := settings.get_strv("trusted-domains")).remove(domain)
        except ValueError:
            return

        settings.set_strv("trusted-domains", current)

    def _build_domains(self, *_args):
        while self._domain_rows:
            self.domains.remove(self._domain_rows.pop())

        for domain in settings.get_strv("trusted-domains"):
            remove_button = Gtk.Button(
                icon_name="edit-delete-symbolic",
                tooltip_text=_("Remove"),
                valign=Gtk.Align.CENTER,
                has_frame=False,
            )

            remove_button.connect(
                "clicked",
                lambda _obj, domain: self._remove_domain(domain),  # pyright: ignore[reportUnknownArgumentType]
                domain,
            )

            self.domains.add(row := Adw.ActionRow(title=domain))
            row.add_suffix(remove_button)
            self._domain_rows.append(row)
