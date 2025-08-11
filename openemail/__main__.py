# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: Copyright 2025 Mercata Sagl
# SPDX-FileContributor: kramo

import sys

from gi.events import GLibEventLoopPolicy

from .application import Application

with GLibEventLoopPolicy():
    sys.exit(Application().run(sys.argv))
