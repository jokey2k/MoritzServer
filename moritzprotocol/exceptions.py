# -*- coding: utf-8 -*-
"""
    moritzprotocol.exceptions
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    All known exceptions related to Moritz communications

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports

# environment imports

# custom imports

# local constants

class MoritzError(Exception):
	"""Our base class for all errors"""

	pass


class UnknownMessageError(MoritzError):
	"""Unhandled message ID received"""

	pass


class LengthNotMatchingError(MoritzError):
	"""Message payload length and indicated length differ"""

	pass


class MissingPayloadParameterError(MoritzError):
	"""Parameter missing to construct message"""

	pass


