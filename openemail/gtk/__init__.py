"""GTK widgets for OpenEmail."""

from pathlib import Path

from gi.repository import Gio

from openemail import PKGDATADIR

for resource in ("data", "ui", "icons"):
    resource_path = Path(PKGDATADIR, f"{resource}.gresource")
    Gio.resources_register(Gio.Resource.load(str(resource_path)))
