"""Part of python-OBD (a derivative of pyOBD)."""
########################################################################
#                                                                      #
# python-OBD: A python OBD-II serial module derived from pyobd         #
#                                                                      #
# Copyright 2004 Donour Sizemore (donour@uchicago.edu)                 #
# Copyright 2009 SECONS Ltd. (www.obdtester.com)                       #
# Copyright 2009 Peter J. Creath                                       #
# Copyright 2016 Brendan Whitfield (brendan-w.com)                     #
#                                                                      #
########################################################################
#                                                                      #
# OBDCommand.py                                                        #
#                                                                      #
# This file is part of python-OBD (a derivative of pyOBD)              #
#                                                                      #
# python-OBD is free software: you can redistribute it and/or modify   #
# it under the terms of the GNU General Public License as published by #
# the Free Software Foundation, either version 2 of the License, or    #
# (at your option) any later version.                                  #
#                                                                      #
# python-OBD is distributed in the hope that it will be useful,        #
# but WITHOUT ANY WARRANTY; without even the implied warranty of       #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the        #
# GNU General Public License for more details.                         #
#                                                                      #
# You should have received a copy of the GNU General Public License    #
# along with python-OBD.  If not, see <http://www.gnu.org/licenses/>.  #
#                                                                      #
########################################################################

import logging

from .OBDResponse import OBDResponse
from .utils import isHex

logger = logging.getLogger(__name__)


class OBDCommand:
    """Command object."""

    def __init__(
        self,
        name,
        desc,
        command,
        _bytes,
        decoder,
        header,
        fast=False,
    ) -> None:
        """Initialise."""
        self.name = name  # human readable name (also used as key in commands dict)
        self.desc = desc  # human readable description
        self.command = command  # command string
        self.bytes = _bytes  # number of bytes expected in return
        self.decode = decoder  # decoding function
        self.header = header  # header used for the queries
        self.fast = fast  # can an extra digit be added to the end of the command? (to make the ELM return early)

    def clone(self):
        """Copy constructor."""
        return OBDCommand(
            self.name,
            self.desc,
            self.command,
            self.bytes,
            self.decode,
            self.header,
            self.fast,
        )

    @property
    def mode(self):
        """Return the mode."""
        if len(self.command) >= 2 and isHex(self.command.decode()):
            return int(self.command[:2], 16)
        return None

    @property
    def pid(self):
        """Return the pid."""
        if len(self.command) > 2 and isHex(self.command.decode()):
            return int(self.command[2:], 16)
        return None

    def __call__(self, messages):
        """Decode the message with the relevant decoder."""
        # guarantee data size for the decoder
        for m in messages:
            self.__constrain_message_data(m)

        # create the response object with the raw data received
        # and reference to original command
        r = OBDResponse(self, messages)
        if messages:
            r.value = self.decode(messages)
        else:
            logger.info("%s did not receive any acceptable messages", str(self))

        return r

    def __constrain_message_data(self, message):
        """Pad or chop the data field to the size specified by this command."""
        len_msg_data = len(message.data)
        if self.bytes > 0:
            if len_msg_data > self.bytes:
                # chop off the right side
                message.data = message.data[: self.bytes]
                logger.debug(
                    "Message was longer than expected (%s>%s). Trimmed message: %s",
                    len_msg_data,
                    self.bytes,
                    repr(message.data),
                )
            elif len_msg_data < self.bytes:
                # pad the right with zeros
                message.data += b"\x00" * (self.bytes - len_msg_data)
                logger.debug(
                    "Message was shorter than expected (%s<%s). Padded message: %s",
                    len_msg_data,
                    self.bytes,
                    repr(message.data),
                )

    def __str__(self):
        """Return string representation of command."""
        return str(f"{self.header + self.command}: {self.desc}")

    def __repr__(self):
        """Return representation of the command."""
        return ("OBDCommand" + "(%s, %s, %s, %s, raw_string, fast=%s, header=%s)"), (
            repr(self.name),
            repr(self.desc),
            repr(self.command),
            self.bytes,
            self.fast,
            repr(self.header),
        )

    def __hash__(self):
        """Return the hash of the command."""
        # needed for using commands as keys in a dict (see async.py)
        return hash(self.header + self.command)

    def __eq__(self, other):
        """Equals check."""
        if isinstance(other, OBDCommand):
            return self.command == other.command and self.header == other.header
        return False
