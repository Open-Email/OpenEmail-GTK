# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo
# SPDX-FileContributor: Jamie Gravendeel

import re
from typing import Any, override

from gi.repository import Adw, GObject, Gtk

from openemail import Property
from openemail.core.model import Address
from openemail.store import ADDRESS_SPLIT_PATTERN


class FormField(GObject.Object):
    """A field in a form."""

    __gtype_name__ = __qualname__

    active = Property(bool, default=True)
    valid = Property(bool)

    text = Property(str)

    @Property(Gtk.Widget)
    def field(self) -> Gtk.Widget:
        """The field containing the text."""
        return self._field

    @field.setter
    def field(self, field: Gtk.Widget):
        self._field = field

        buffer = field.props.buffer if isinstance(field, Gtk.TextView) else field
        Property.bind(buffer, "text", self, bidirectional=True)
        buffer.connect("notify::text", lambda *_: self.validate())

    def validate(self):
        """Validate the form field."""
        self.valid = bool(self.text)

    def reset(self):
        """Reset the form field to be empty."""
        self.text = ""


class AddressFormField(FormField):
    """A form field for validating an address."""

    __gtype_name__ = __qualname__

    @override
    def validate(self):
        try:
            Address(self.text)
        except ValueError:
            self.valid = False
        else:
            self.valid = True


class AddressListFormField(FormField):
    """A form field for validating a list of addresses."""

    __gtype_name__ = __qualname__

    @override
    def validate(self):
        try:
            if not any(addresses := re.split(ADDRESS_SPLIT_PATTERN, self.text)):
                raise ValueError

            for address in addresses:
                if address:
                    Address(address)

        except ValueError:
            self.valid = False
        else:
            self.valid = True


class Form(GObject.Object, Gtk.Buildable):  # pyright: ignore[reportIncompatibleMethodOverride]
    """An abstract representation of a form in UI with validation."""

    __gtype_name__ = __qualname__

    submit_widget = Property(Gtk.Widget)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self._fields = list[FormField]()

    @property
    def valid(self) -> bool:
        """Whether all fields in the form are valid."""
        return all(field.valid for field in self._fields if field.active)

    def do_add_child(self, _builder, field: GObject.Object, _type):
        """Add a child to `self`."""
        if not isinstance(field, FormField):
            e = "Children of Form must be FormField"
            raise TypeError(e)

        self._fields.append(field)

    def do_parser_finished(self, *_args):
        """Call when a builder finishes the parsing of a UI definition."""
        for field in self._fields:
            for signal in "notify::valid", "notify::active":
                field.connect(signal, lambda *_: self._update_submit_widget())

            field.validate()

    def _update_submit_widget(self):
        match widget := self.submit_widget:
            case Adw.AlertDialog():
                if not (default := widget.props.default_response):
                    e = "submit-widget must have Adw.AlertDialog:default-response"
                    raise ValueError(e)

                widget.set_response_enabled(default, self.valid)

            case Adw.EntryRow():
                if self.valid:
                    widget.remove_css_class("error")
                else:
                    widget.add_css_class("error")

            case Gtk.Widget():
                widget.props.sensitive = self.valid

    def reset(self):
        """Reset the state of the form.

        Useful for reusable widgets after submission.
        """
        for field in self._fields:
            field.reset()
