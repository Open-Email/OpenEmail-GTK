# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GLib, GObject, Gtk

import openemail as app
from openemail import PREFIX, Message, Property
from openemail.store import DictStore

from .compose_sheet import ComposeSheet
from .page import Page
from .thread_view import ThreadView

GObject.type_ensure(Page)
GObject.type_ensure(ThreadView)


class _Messages(Adw.NavigationPage):
    def __init__(
        self,
        model: Gio.ListModel,
        /,
        *,
        title: str,
        subtitle: str = "",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)

        self.builder = Gtk.Builder.new_from_resource(f"{PREFIX}/messages.ui")

        self.trashed: Gtk.BoolFilter = self._get_object("trashed")
        app.settings.connect("changed::trashed-messages", self._on_trash_changed)
        self._get_object("sort_model").props.model = model

        self.thread_view: ThreadView = self._get_object("thread_view")
        self.thread_view.connect(
            "reply", lambda _, msg: ComposeSheet.default.reply(msg)
        )

        self.page: Page = self._get_object("page")
        self.page.title = self.props.title = title
        self.page.subtitle = subtitle
        self.page.model.connect("notify::selected", self._on_selected)
        self.page.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/message-row.ui"
        )

        self.props.child = self.page

    def _get_object(self, name: str) -> Any:  # noqa: ANN401
        return self.builder.get_object(name)

    def _on_trash_changed(self, *_args):
        props.autoselect = (props := self.page.model.props).selected != GLib.MAXUINT
        self.trashed.changed(Gtk.FilterChange.DIFFERENT)
        props.autoselect = False

    def _on_selected(self, selection: Gtk.SingleSelection, *_args):
        if (msg := selection.props.selected_item) and not isinstance(msg, Message):
            return

        self.thread_view.message = msg
        if isinstance(msg, Message):
            msg.mark_read()
            self.page.split_view.props.show_content = True


class _Folder(_Messages):
    folder: DictStore[str, Message]
    title: str
    subtitle: str = ""

    def __init__(self, **kwargs: Any):
        super().__init__(
            self.folder,
            title=self.title,
            subtitle=self.subtitle,
            **kwargs,
        )

        self.page.toolbar_button = self._get_object("toolbar_new")
        self.page.empty_page = self._get_object("no_messages")
        Property.bind(self.page.model, "selected-item", self.thread_view, "message")

        for button in self.page.toolbar_button, self._get_object("new_button"):
            button.connect("clicked", lambda *_: ComposeSheet.default.new_message())

        Property.bind(self.folder, "updating", self.page, "loading")


class Inbox(_Folder):
    """A navigation page displaying the user's inbox."""

    __gtype_name__ = "Inbox"
    folder, title = app.inbox, _("Inbox")


class Outbox(_Folder):
    """A navigation page displaying the user's outbox."""

    __gtype_name__ = "Outbox"
    folder, title, subtitle = app.outbox, _("Outbox"), _("Can be discarded")


class Sent(_Folder):
    """A navigation page displaying the user's sent messages."""

    __gtype_name__ = "Sent"
    folder, title, subtitle = app.sent, _("Sent"), _("From this device")


class Drafts(_Messages):
    """A navigation page displaying the user's drafts."""

    __gtype_name__ = "Drafts"

    def __init__(self, **kwargs: Any):
        super().__init__(app.drafts, title=_("Drafts"), **kwargs)

        self.page.model.props.can_unselect = True

        delete_dialog: Adw.AlertDialog = self._get_object("delete_dialog")
        delete_dialog.connect("response::delete", lambda *_: app.drafts.delete_all())

        delete_button: Gtk.Button = self._get_object("delete_button")
        delete_button.connect("clicked", lambda *_: delete_dialog.present(self))
        self.page.toolbar_button = delete_button

        self.page.empty_page = self._get_object("no_drafts")
        Property.bind(self.page.model, "n-items", delete_button, "sensitive")

    def _on_selected(self, selection: Gtk.SingleSelection, *_args):
        if isinstance(msg := selection.props.selected_item, Message):
            selection.unselect_all()
            ComposeSheet.default.open_draft(msg)


class Trash(_Messages):
    """A navigation page displaying the user's trash folder."""

    __gtype_name__ = "Trash"

    def __init__(self, **kwargs: Any):
        super().__init__(
            Gtk.FlattenListModel.new(folders := Gio.ListStore.new(Gio.ListModel)),
            title=_("Trash"),
            subtitle=_("On this device"),
            **kwargs,
        )

        self.trashed.props.invert = False

        folders.append(app.broadcasts)
        folders.append(app.inbox)
        folders.append(app.sent)

        empty_dialog: Adw.AlertDialog = self._get_object("empty_dialog")
        empty_dialog.connect("response::empty", lambda *_: app.empty_trash())

        empty_button: Gtk.Button = self._get_object("empty_button")
        empty_button.connect("clicked", lambda *_: empty_dialog.present(self))
        self.page.toolbar_button = empty_button

        self.page.empty_page = self._get_object("empty_trash")
        Property.bind(self.page.model, "selected-item", self.thread_view, "message")
        Property.bind(self.page.model, "n-items", empty_button, "sensitive")

        def set_loading(*_args):
            self.page.loading = app.inbox.updating or app.broadcasts.updating

        app.inbox.connect("notify::updating", set_loading)
        app.broadcasts.connect("notify::updating", set_loading)


class Broadcasts(_Folder):
    """A navigation page displaying the user's broadcasts folder."""

    __gtype_name__ = "Broadcasts"
    folder, title = app.broadcasts, _("Public")
