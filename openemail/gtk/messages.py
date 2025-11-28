# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

from typing import Any, override

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from openemail import PREFIX, Property, store
from openemail.message import Message
from openemail.store import DictStore

from .page import Page
from .thread_view import ThreadView

for t in Page, ThreadView:
    GObject.type_ensure(t)


@Gtk.Template.from_resource(f"{PREFIX}/message-row.ui")
class MessageRow(Gtk.Box):
    """A row representing a message."""

    __gtype_name__ = __qualname__

    context_menu = Gtk.Template.Child()

    @Property[Message | None](Message)
    def message(self) -> Message | None:
        """The message that `self` represents."""  # noqa: D401
        return self._message

    @message.setter
    def message(self, msg: Message | None):
        self._message = msg
        self.insert_action_group("message", msg)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

        self.insert_action_group("row", group := Gio.SimpleActionGroup())

        reply = Gio.SimpleAction.new("reply")
        reply.connect("activate", lambda *_: self._reply())

        message = Gtk.PropertyExpression.new(MessageRow, None, "message")
        can_reply = Gtk.PropertyExpression.new(Message, message, "can-reply")
        can_reply.bind(reply, "enabled", self)

        group.add_action(reply)

    def _reply(self):
        ident = GLib.Variant.new_string(self.message.unique_id)
        self.activate_action("compose.reply", ident)

    @Gtk.Template.Callback()
    def _show_context_menu(self, _gesture, _n_press: int, x: float, y: float):
        if self.message.is_draft:
            return

        rect = Gdk.Rectangle()
        rect.x, rect.y = int(x), int(y)
        self.context_menu.props.pointing_to = rect
        self.context_menu.popup()


class _Messages(Adw.NavigationPage):
    counter = Property(int)

    _count_unread = False

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
        store.settings.connect("changed::trashed-messages", self._on_trash_changed)

        self._get_object("sort_model").props.model = model
        self.thread_view: ThreadView = self._get_object("thread_view")

        self.page: Page = self._get_object("page")
        self.page.title = self.props.title = title
        self.page.subtitle = subtitle
        self.page.model.connect("notify::selected", self._on_selected)

        self.props.child = self.page

        if not self._count_unread:
            return

        unread: Gtk.FilterListModel = self._get_object("unread")
        unread.bind_property(
            "n-items", self, "counter", GObject.BindingFlags.SYNC_CREATE
        )

        unread_filter = self._get_object("unread_filter")
        store.settings.connect(
            "changed::unread-messages",
            lambda *_: unread_filter.changed(Gtk.FilterChange.DIFFERENT),
        )

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
            msg.unread = False
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
        Property.bind(self.folder, "updating", self.page, "loading")


class Inbox(_Folder):
    """A navigation page displaying the user's inbox."""

    __gtype_name__ = __qualname__
    folder, title = store.inbox, _("Inbox")

    _count_unread = True


class Outbox(_Folder):
    """A navigation page displaying the user's outbox."""

    __gtype_name__ = __qualname__
    folder, title, subtitle = store.outbox, _("Outbox"), _("Can be discarded")


class Sent(_Folder):
    """A navigation page displaying the user's sent messages."""

    __gtype_name__ = __qualname__
    folder, title, subtitle = store.sent, _("Sent"), _("From this device")


class Drafts(_Messages):
    """A navigation page displaying the user's drafts."""

    __gtype_name__ = __qualname__

    @override
    @Property(int)
    def counter(self) -> int:
        return len(store.drafts)

    def __init__(self, **kwargs: Any):
        super().__init__(store.drafts, title=_("Drafts"), **kwargs)

        self.page.model.props.can_unselect = True

        delete_dialog: Adw.AlertDialog = self._get_object("delete_dialog")
        delete_dialog.connect("response::delete", lambda *_: store.drafts.delete_all())

        delete_button: Gtk.Button = self._get_object("delete_button")
        delete_button.connect("clicked", lambda *_: delete_dialog.present(self))
        self.page.toolbar_button = delete_button

        self.page.empty_page = self._get_object("no_drafts")
        Property.bind(self.page.model, "n-items", delete_button, "sensitive")

        store.drafts.connect("items-changed", lambda *_: self.notify("counter"))

    def _on_selected(self, selection: Gtk.SingleSelection, *_args):
        if isinstance(msg := selection.props.selected_item, Message):
            selection.unselect_all()
            self.activate_action(
                "compose.draft", GLib.Variant.new_string(msg.unique_id)
            )


class Trash(_Messages):
    """A navigation page displaying the user's trash folder."""

    __gtype_name__ = __qualname__

    model = store.flatten(store.inbox, store.sent, store.broadcasts)

    _count_unread = True

    def __init__(self, **kwargs: Any):
        super().__init__(
            self.model,
            title=_("Trash"),
            subtitle=_("On this device"),
            **kwargs,
        )

        self.trashed.props.invert = False

        empty_dialog: Adw.AlertDialog = self._get_object("empty_dialog")
        empty_dialog.connect("response::empty", lambda *_: store.empty_trash())

        empty_button: Gtk.Button = self._get_object("empty_button")
        empty_button.connect("clicked", lambda *_: empty_dialog.present(self))
        self.page.toolbar_button = empty_button

        self.page.empty_page = self._get_object("empty_trash")
        Property.bind(self.page.model, "selected-item", self.thread_view, "message")
        Property.bind(self.page.model, "n-items", empty_button, "sensitive")

        def set_loading(*_args):
            self.page.loading = store.inbox.updating or store.broadcasts.updating

        store.inbox.connect("notify::updating", set_loading)
        store.broadcasts.connect("notify::updating", set_loading)


class Broadcasts(_Folder):
    """A navigation page displaying the user's broadcasts folder."""

    __gtype_name__ = __qualname__
    folder, title = store.broadcasts, _("Public")

    _count_unread = True
