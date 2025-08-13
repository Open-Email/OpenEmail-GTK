# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

from typing import Any

from gi.repository import Adw, Gio, GLib, GObject, Gtk

import openemail as app
from openemail import PREFIX, Message, empty_trash, settings

from .compose_sheet import ComposeSheet
from .page import Page
from .thread_view import ThreadView

GObject.type_ensure(Page)
GObject.type_ensure(ThreadView)


class _Messages(Adw.NavigationPage):
    def __init__(self, model: Gio.ListModel, /, *, title: str, **kwargs: Any):
        super().__init__(**kwargs)

        self.builder = Gtk.Builder.new_from_resource(f"{PREFIX}/messages.ui")

        self.trashed: Gtk.BoolFilter = self._get_object("trashed")
        settings.connect("changed::trashed-messages", self._on_trash_changed)
        self._get_object("sort_model").props.model = model

        self.thread_view: ThreadView = self._get_object("thread_view")
        self.thread_view.connect(
            "reply",
            lambda _, msg: ComposeSheet.default.reply(msg),
        )

        self.content: Page = self._get_object("content")
        self.content.title = self.props.title = title
        self.content.model.connect("notify::selected", self._on_selected)
        self.content.factory = Gtk.BuilderListItemFactory.new_from_resource(
            None, f"{PREFIX}/message-row.ui"
        )

        self.props.child = self.content

    def _get_object(self, name: str) -> Any:  # noqa: ANN401
        return self.builder.get_object(name)

    def _on_trash_changed(self, *_args):
        m.autoselect = (m := self.content.model.props).selected != GLib.MAXUINT
        self.trashed.changed(Gtk.FilterChange.DIFFERENT)
        m.autoselect = False

    def _on_selected(self, selection: Gtk.SingleSelection, *_args):
        self.thread_view.message = (message := selection.props.selected_item)
        if not isinstance(message, Message):
            return

        message.mark_read()
        self.content.split_view.props.show_content = True


class _Folder(_Messages):
    folder: Gio.ListModel
    title: str

    def __init__(self, **kwargs: Any):
        super().__init__(self.folder, title=self.title, **kwargs)

        self.content.toolbar_button = self._get_object("toolbar_new")
        self.content.empty_page = self._get_object("no_messages")
        self.content.model.bind_property("selected-item", self.thread_view, "message")

        for button in (self.content.toolbar_button, self._get_object("new_button")):
            button.connect("clicked", lambda *_: ComposeSheet.default.new_message())

        self.folder.bind_property(
            "updating",
            self.content,
            "loading",
            GObject.BindingFlags.SYNC_CREATE,
        )


class Inbox(_Folder):
    """A navigation page displaying the user's inbox."""

    __gtype_name__ = "Inbox"
    folder, title = app.inbox, _("Inbox")


class Outbox(_Folder):
    """A navigation page displaying the user's outbox."""

    __gtype_name__ = "Outbox"
    folder, title = app.outbox, _("Outbox")


class Drafts(_Messages):
    """A navigation page displaying the user's drafts."""

    __gtype_name__ = "Drafts"

    def __init__(self, **kwargs: Any):
        super().__init__(app.drafts, title=_("Drafts"), **kwargs)

        self.content.model.props.can_unselect = True

        delete_dialog: Adw.AlertDialog = self._get_object("delete_dialog")
        delete_dialog.connect("response::delete", lambda *_: app.drafts.delete_all())

        delete_button: Gtk.Button = self._get_object("delete_button")
        delete_button.connect("clicked", lambda *_: delete_dialog.present(self))
        self.content.toolbar_button = delete_button

        self.content.empty_page = self._get_object("no_drafts")
        self.content.model.bind_property(
            "n-items",
            delete_button,
            "sensitive",
            GObject.BindingFlags.SYNC_CREATE,
        )

    def _on_selected(self, selection: Gtk.SingleSelection, *_args):
        if not isinstance(msg := selection.props.selected_item, Message):
            return

        selection.unselect_all()
        ComposeSheet.default.open_message(msg)


class Trash(_Messages):
    """A navigation page displaying the user's trash folder."""

    __gtype_name__ = "Trash"

    def __init__(self, **kwargs: Any):
        super().__init__(
            Gtk.FlattenListModel.new(folders := Gio.ListStore.new(Gio.ListModel)),
            title=_("Trash"),
            **kwargs,
        )

        self.trashed.props.invert = False

        folders.append(app.broadcasts)
        folders.append(app.inbox)

        empty_dialog: Adw.AlertDialog = self._get_object("empty_dialog")
        empty_dialog.connect("response::empty", lambda *_: empty_trash())

        empty_button: Gtk.Button = self._get_object("empty_button")
        empty_button.connect("clicked", lambda *_: empty_dialog.present(self))
        self.content.toolbar_button = empty_button

        self.content.empty_page = self._get_object("empty_trash")
        self.content.model.bind_property("selected-item", self.thread_view, "message")
        self.content.model.bind_property(
            "n-items",
            empty_button,
            "sensitive",
            GObject.BindingFlags.SYNC_CREATE,
        )

        def set_loading(*_args):
            self.content.loading = app.inbox.updating or app.broadcasts.updating

        app.inbox.connect("notify::updating", set_loading)
        app.broadcasts.connect("notify::updating", set_loading)


class Broadcasts(_Folder):
    """A navigation page displaying the user's broadcasts folder."""

    __gtype_name__ = "Broadcasts"
    folder, title = app.broadcasts, _("Public")
