# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileCopyrightText: Copyright 2025 OpenEmail SA
# SPDX-FileContributor: kramo

import sys

from gi.events import GLibEventLoopPolicy

from .gtk.application import Application

with GLibEventLoopPolicy():
    sys.exit(Application().run(sys.argv))
