# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import re
from contextlib import suppress
from enum import Enum
from typing import Any

from gi.repository import Adw, GObject, Gtk

from openemail.mail import Address


class FormField(Enum):
    """A type of field in a form."""

    PLAIN = 1
    ADDRESS = 2
    ADDRESS_LIST = 3


class Form(GObject.Object):
    """An abstract representation of a form in UI with validation."""

    __gtype_name__ = "Form"

    form = GObject.Property(type=Gtk.Widget)
    submit = GObject.Property(type=GObject.Object)

    invalid: set[Gtk.Editable | Gtk.TextBuffer]

    _fields: dict[FormField, Gtk.StringList]

    @GObject.Property(type=Gtk.StringList)
    def plain(self) -> Gtk.StringList | None:
        """Get the plain, text-only fields of the form."""
        return self._fields.get(FormField.PLAIN)

    @plain.setter
    def plain(self, fields: Gtk.StringList) -> None:
        self._assign_fields(FormField.PLAIN, fields)

    @GObject.Property(type=Gtk.StringList)
    def addresses(self) -> Gtk.StringList | None:
        """Get fields of the form for addresses."""
        return self._fields.get(FormField.ADDRESS)

    @addresses.setter
    def addresses(self, fields: Gtk.StringList) -> None:
        self._assign_fields(FormField.ADDRESS, fields)

    @GObject.Property(type=Gtk.StringList)
    def address_lists(self) -> Gtk.StringList | None:
        """Get fields of the form for comma-separated lists of addresses."""
        return self._fields.get(FormField.ADDRESS_LIST)

    @address_lists.setter
    def address_lists(self, fields: Gtk.StringList) -> None:
        self._assign_fields(FormField.ADDRESS_LIST, fields)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fields = {}

    def reset(self) -> None:
        """Reset the state of the form.

        Useful for reusable widgets after submission.
        """
        for fields in self._fields.values():
            for field in fields:
                try:
                    getattr(self.form, field.props.string).props.text = ""
                except AttributeError:
                    continue

    def _assign_fields(self, form_field: FormField, fields: Gtk.StringList) -> None:
        self._fields[form_field] = fields

        if self.form.get_realized():
            self._setup()
            return

        self.form.connect("realize", self._setup)

    def _setup(self, *_args: Any) -> None:
        with suppress(TypeError):
            self.form.disconnect_by_func(self._setup)

        self.invalid = set()

        for form_field, fields in self._fields.items():
            for field in fields:
                try:
                    widget = getattr(self.form, field.props.string)
                except AttributeError:
                    continue

                widget.connect("changed", self._validate, form_field)
                self._validate(widget, form_field)

        self._verify()

    def _validate(
        self,
        field: Gtk.Editable | Gtk.TextBuffer,
        form_field: FormField,
    ) -> None:
        text = field.props.text

        match form_field:
            case FormField.PLAIN:
                (self._valid if text else self._invalid)(field)

            case FormField.ADDRESS:
                try:
                    Address(text)
                except ValueError:
                    self._invalid(field)
                    return

                self._valid(field)

            case FormField.ADDRESS_LIST:
                if not (
                    addresses := tuple(
                        address for address in re.split(",|;| ", text) if address
                    )
                ):
                    self._invalid(field)
                    return

                for address in addresses:
                    try:
                        Address(address)
                    except ValueError:
                        self._invalid(field)
                        return

                self._valid(field)

    def _verify(self) -> None:
        if isinstance(self.submit, Adw.AlertDialog):
            if not (default := self.submit.props.default_response):
                return

            self.submit.set_response_enabled(default, not self.invalid)
            return

        if isinstance(self.submit, Adw.EntryRow):
            (
                self.submit.add_css_class
                if self.invalid
                else self.submit.remove_css_class
            )("error")
            return

        if isinstance(self.submit, Gtk.Widget):
            self.submit.props.sensitive = not self.invalid

    def _valid(self, editable: Gtk.Editable | Gtk.TextBuffer) -> None:
        self.invalid.discard(editable)
        self._verify()

    def _invalid(self, editable: Gtk.Editable | Gtk.TextBuffer) -> None:
        self.invalid.add(editable)
        self._verify()
