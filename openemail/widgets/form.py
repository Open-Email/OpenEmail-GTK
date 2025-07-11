# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo
# SPDX-FileContributor: Jamie Gravendeel

import re
from typing import Any, cast

from gi.repository import Adw, GObject, Gtk

from openemail.lib.mail import ADDRESS_SPLIT_PATTERN, Address


class FormFieldType(GObject.GEnum):
    """A type of form field."""

    PLAIN = 0
    ADDRESS = 1
    ADDRESS_LIST = 2


class FormField(GObject.Object):
    """A field in a form."""

    __gtype_name__ = "FormField"

    type = GObject.Property(type=FormFieldType, default=FormFieldType.PLAIN)

    active = GObject.Property(type=bool, default=True)
    valid = GObject.Property(type=bool, default=False)

    text = GObject.Property(type=str)

    @GObject.Property(type=Gtk.Widget)
    def field(self) -> Gtk.Widget:
        """Get the field containing the text."""
        return self._field

    @field.setter
    def field(self, field: Gtk.Widget) -> None:
        if isinstance(field, Gtk.Editable):
            field.bind_property(
                "text", self, "text", GObject.BindingFlags.BIDIRECTIONAL
            )
            field.connect("notify::text", lambda *_: self.validate())
        elif isinstance(field, Gtk.TextView):
            field.props.buffer.bind_property(
                "text", self, "text", GObject.BindingFlags.BIDIRECTIONAL
            )
            field.props.buffer.connect("notify::text", lambda *_: self.validate())
        else:
            msg = "FormField.field must be Gtk.Editable or Gtk.TextView"
            raise TypeError(msg)

        self._field = field

    def validate(self) -> None:
        """Validate the form field."""
        match cast("FormFieldType", self.type):
            case FormFieldType.PLAIN:
                self.valid = bool(self.text)

            case FormFieldType.ADDRESS:
                try:
                    Address(self.text)
                except ValueError:
                    self.valid = False
                else:
                    self.valid = True

            case FormFieldType.ADDRESS_LIST:
                if not (addresses := re.split(ADDRESS_SPLIT_PATTERN, self.text)):
                    self.valid = False
                    return

                try:
                    for address in addresses:
                        Address(address)
                except ValueError:
                    self.valid = False
                else:
                    self.valid = True

    def reset(self) -> None:
        """Reset the form field."""
        self.text = ""


class Form(GObject.Object, Gtk.Buildable):  # pyright: ignore[reportIncompatibleMethodOverride]
    """An abstract representation of a form in UI with validation."""

    __gtype_name__ = "Form"

    submit_widget = GObject.Property(type=Gtk.Widget)

    def __init__(self) -> None:
        super().__init__()

        self._fields = list[FormField]()

    @property
    def valid(self) -> bool:
        """Whether all fields in the form are valid."""
        return all(field.valid for field in self._fields if field.active)

    def do_add_child(self, _builder: Any, field: GObject.Object, _type: Any) -> None:
        """Add a child to `self`."""
        if not isinstance(field, FormField):
            msg = "Children of Form must be FormField"
            raise TypeError(msg)

        self._fields.append(field)

    def do_parser_finished(self, *_args: Any) -> None:
        """Call when a builder finishes the parsing of a UI definition."""
        for field in self._fields:
            field.connect("notify::valid", lambda *_: self._update_submit_widget())
            field.connect("notify::active", lambda *_: self._update_submit_widget())
            field.validate()

    def _update_submit_widget(self) -> None:
        if isinstance(self.submit_widget, Adw.AlertDialog):
            if not (default := self.submit_widget.props.default_response):
                msg = "Form.submit-widget as Adw.AlertDialog must have default-response"
                raise AttributeError(msg)

            self.submit_widget.set_response_enabled(default, self.valid)

        elif isinstance(self.submit_widget, Adw.EntryRow):
            if self.valid:
                self.submit_widget.remove_css_class("error")
            else:
                self.submit_widget.add_css_class("error")

        elif self.submit_widget:
            self.submit_widget.props.sensitive = self.valid

    def reset(self) -> None:
        """Reset the state of the form.

        Useful for reusable widgets after submission.
        """
        for field in self._fields:
            field.reset()
