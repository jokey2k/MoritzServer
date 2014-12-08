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
device_pair_request = signal('device_pair_request')
device_pair_accepted = signal('device_pair_accepted')

thermostatstate_received = signal('thermostatstate_received')
