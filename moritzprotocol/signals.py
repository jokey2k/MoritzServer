# -*- coding: utf-8 -*-
"""
    moritzprotocol.signals
    ~~~~~~~~~~~~~~~~~~~~~~

    Hooks into communication with Moritz hardware

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports

# environment imports
from blinker import signal

# custom imports

# local constants

thermostatstate_received = signal('thermostatstate_received')
