"""Part of python-OBD (a derivative of pyOBD)."""

########################################################################
#                                                                      #
# python-OBD: A python OBD-II serial module derived from pyobd         #
#                                                                      #
# Copyright 2004 Donour Sizemore (donour@uchicago.edu)                 #
# Copyright 2009 Seconds Ltd. (www.obdtester.com)                       #
# Copyright 2009 Peter J. Creath                                       #
# Copyright 2016 Brendan Whitfield (brendan-w.com)                     #
#                                                                      #
########################################################################
#                                                                      #
# elm327.py                                                            #
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

import asyncio
import logging
import re

from bleak.backends.device import BLEDevice

from .bleserial import bleserial
from .protocols.protocol import Message
from .protocols.protocol_can import ISO_15765_4_11bit_500k

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class OBDStatus:
    """Values for the connection status flags."""

    NOT_CONNECTED = "Not Connected"
    ELM_CONNECTED = "ELM Connected"
    OBD_CONNECTED = "OBD Connected"
    CAR_CONNECTED = "Car Connected"


class ELM327:
    """Handles communication with the ELM327 adapter."""

    # chevron (ELM prompt character)
    ELM_PROMPT = b">"
    # an 'OK' which indicates we are entering low power state
    ELM_LP_ACTIVE = b"OK"

    # GATT UUIDs specifically for LeLink OBD BLE dongle
    SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
    CHARACTERISTIC_UUID_READ = "0000ffe1-0000-1000-8000-00805f9b34fb"
    CHARACTERISTIC_UUID_WRITE = "0000ffe1-0000-1000-8000-00805f9b34fb"

    # GATT UUIDs for Veepeak/Vgate style adapters
    VEEPEAK_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
    VEEPEAK_CHARACTERISTIC_UUID_READ = "0000fff1-0000-1000-8000-00805f9b34fb"
    VEEPEAK_CHARACTERISTIC_UUID_WRITE = "0000fff1-0000-1000-8000-00805f9b34fb"

    # GATT UUIDs for devices using the Nordic UART Service
    NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    NUS_CHARACTERISTIC_UUID_READ = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
    NUS_CHARACTERISTIC_UUID_WRITE = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    def __init__(
        self,
        device: BLEDevice,
        timeout,
        service_uuid: str = SERVICE_UUID,
        characteristic_uuid_read: str = CHARACTERISTIC_UUID_READ,
        characteristic_uuid_write: str = CHARACTERISTIC_UUID_WRITE,
    ) -> None:
        """Initialise."""
        self.__status = OBDStatus.NOT_CONNECTED
        self.__low_power = False
        self.timeout = timeout
        self.__port = bleserial(
            device,
            service_uuid,
            characteristic_uuid_read,
            characteristic_uuid_write,
        )
        self.__protocol = ISO_15765_4_11bit_500k()

    @classmethod
    async def create(
        cls,
        device: BLEDevice,
        protocol,
        timeout,
        check_voltage=True,
        start_low_power=False,
    ):
        """Initialize ELM327."""
        uuids = [u.lower() for u in (device.metadata or {}).get("uuids", [])]

        service_uuid = cls.SERVICE_UUID
        characteristic_uuid_read = cls.CHARACTERISTIC_UUID_READ
        characteristic_uuid_write = cls.CHARACTERISTIC_UUID_WRITE

        if cls.NUS_SERVICE_UUID in uuids:
            service_uuid = cls.NUS_SERVICE_UUID
            characteristic_uuid_read = cls.NUS_CHARACTERISTIC_UUID_READ
            characteristic_uuid_write = cls.NUS_CHARACTERISTIC_UUID_WRITE
        elif cls.VEEPEAK_SERVICE_UUID in uuids:
            service_uuid = cls.VEEPEAK_SERVICE_UUID
            characteristic_uuid_read = cls.VEEPEAK_CHARACTERISTIC_UUID_READ
            characteristic_uuid_write = cls.VEEPEAK_CHARACTERISTIC_UUID_WRITE

        self = cls(
            device,
            timeout,
            service_uuid,
            characteristic_uuid_read,
            characteristic_uuid_write,
        )

        logger.info(
            "Initializing ELM327: PROTOCOL=%s",
            ("auto" if protocol is None else protocol,),
        )

        # ------------- open port -------------
        try:
            await self.__port.open()
        except Exception:
            logger.warning(
                "An error occurred: %s", ("auto" if protocol is None else protocol,)
            )
            return self

        # If we start with the IC in the low power state we need to wake it up
        if start_low_power:
            await self.__write(b" ")
            await asyncio.sleep(1)

        # ---------------------------- ATZ (reset) ----------------------------
        try:
            await self.__send(b"ATZ", delay=1)  # wait 1 second for ELM to initialize
            # return data can be junk, so don't bother checking
        except Exception as e:
            await self.__error(e)
            return self

        # -------------------------- ATE0 (echo OFF) --------------------------
        r = await self.__send(b"ATE0")
        if not self.__isok(r, expectEcho=True):
            await self.__error("ATE0 did not return 'OK'")
            return self

        # ------------------------ ATSP6 (set protocol 6) ---------------------
        r = await self.__send(b"ATSP6")
        if not self.__isok(r):
            await self.__error("ATSP6 did not return 'OK'")
            return self

        # ------------------------- ATH1 (headers ON) -------------------------
        r = await self.__send(b"ATH1")
        if not self.__isok(r):
            await self.__error("ATH1 did not return 'OK', or echoing is still ON")
            return self

        # ------------------------ ATL0 (linefeeds OFF) -----------------------
        r = await self.__send(b"ATL0")
        if not self.__isok(r):
            await self.__error("ATL0 did not return 'OK'")
            return self

        # ------------------------ ATS0 (printing spaces OFF)------------------
        r = await self.__send(b"ATS0")
        if not self.__isok(r):
            await self.__error("ATS0 did not return 'OK'")
            return self

        # ----------------- ATCAF0 (CAN automatic formatting OFF)--------------
        r = await self.__send(b"ATCAF0")
        if not self.__isok(r):
            await self.__error("ATCAF0 did not return 'OK'")
            return self

        # by now, we've successfully communicated with the ELM, but not the car
        self.__status = OBDStatus.ELM_CONNECTED

        # -------------------------- AT RV (read volt) ------------------------
        if check_voltage:
            r = await self.__send(b"AT RV")
            if not r or len(r) != 1 or r[0] == "":
                await self.__error("No answer from 'AT RV'")
                return self
            try:
                if float(r[0].lower().replace("v", "")) < 6:
                    logger.error("OBD2 socket disconnected")
                    return self
            except ValueError:
                await self.__error("Incorrect response from 'AT RV'")
                return self
            # by now, we've successfully connected to the OBD socket
            self.__status = OBDStatus.OBD_CONNECTED

        # try to communicate with the car, and load the correct protocol parser
        self.__status = OBDStatus.CAR_CONNECTED
        return self

    def __isok(self, lines, expectEcho=False):
        if not lines:
            return False
        if expectEcho:
            # don't test for the echo itself
            # allow the adapter to already have echo disabled
            return self.__has_message(lines, "OK")
        return len(lines) == 1 and lines[0] == "OK"

    def __has_message(self, lines, text):
        return any(text in line for line in lines)

    async def __error(self, msg):
        """Handle fatal failures, print logger.info info and closes serial."""
        await self.close()
        logger.error(str(msg))

    def status(self):
        """Return the status."""
        return self.__status

    def protocol_name(self):
        """Return the protocol name."""
        return self.__protocol.ELM_NAME

    def protocol_id(self):
        """Return the protocol ID."""
        return self.__protocol.ELM_ID

    async def low_power(self):
        """Enter Low Power mode.

        This command causes the ELM327 to shut off all but essential
        services.

        The ELM327 can be woken up by a message to the RS232 bus as
        well as a few other ways. See the Power Control section in
        the ELM327 datasheet for details on other ways to wake up
        the chip.

        Returns the status from the ELM327, 'OK' means low power mode
        is going to become active.
        """

        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot enter low power when unconnected")
            return None

        lines = await self.__send(b"ATLP", delay=1, end_marker=self.ELM_LP_ACTIVE)

        if "OK" in lines:
            logger.debug("Successfully entered low power mode")
            self.__low_power = True
        else:
            logger.debug("Failed to enter low power mode")

        return lines

    async def normal_power(self):
        """Exit Low Power mode.

        Send a space to trigger the RS232 to wakeup.

        This will send a space even if we aren't in low power mode as
        we want to ensure that we will be able to leave low power mode.

        See the Power Control section in the ELM327 datasheet for details
        on other ways to wake up the chip.

        Returns the status from the ELM327.
        """
        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot exit low power when unconnected")
            return None

        lines = await self.__send(b" ")

        # Assume we woke up
        logger.debug("Successfully exited low power mode")
        self.__low_power = False

        return lines

    async def close(self):
        """Reset the device, and sets all attributes to unconnected states."""

        self.__status = OBDStatus.NOT_CONNECTED

        if self.__port is not None:
            logger.info("closing port")
            await self.__write(b"ATZ")
            await self.__port.close()
            self.__port = None

    #  -> list[Message]:
    async def send_and_parse(self, cmd) -> list[Message]:
        """Send OBDCommands.

        Sends the given command string, and parses the
        response lines with the protocol object.

        An empty command string will re-trigger the previous command

        Returns a list of Message objects
        """

        if self.__status == OBDStatus.NOT_CONNECTED:
            logger.info("cannot send_and_parse() when unconnected")
            return None

        # Check if we are in low power
        if self.__low_power:
            await self.normal_power()

        lines = await self.__send(cmd)
        return self.__protocol(lines)

    async def __send(self, cmd, delay=None, end_marker=ELM_PROMPT):
        """Unprotected send() function.

        will __write() the given string, no questions asked.
        returns result of __read() (a list of line strings)
        after an optional delay, until the end marker (by
        default, the prompt) is seen
        """
        await self.__write(cmd)

        delayed = 0.0
        if delay is not None:
            logger.debug("wait: %d seconds", delay)
            await asyncio.sleep(delay)
            delayed += delay

        r = await self.__read(end_marker=end_marker)
        while delayed < 1.0 and len(r) <= 0:
            d = 0.1
            logger.debug("no response; wait: %f seconds", d)
            await asyncio.sleep(d)
            delayed += d
            r = await self.__read(end_marker=end_marker)
        return r

    async def __write(self, cmd):
        """Low-level function to write a string to the port."""

        if self.__port:
            cmd += b"\r"  # terminate with carriage return in accordance with ELM327 and STN11XX specifications
            logger.debug("write: " + repr(cmd))
            try:
                self.__port.reset_input_buffer()  # dump everything in the input buffer
                await self.__port.write(cmd)  # turn the string into bytes and write
                # self.__port.flush()  # wait for the output buffer to finish transmitting
            except Exception as e:
                logger.critical("Device disconnected while writing: %s", e)
                self.__status = OBDStatus.NOT_CONNECTED
                await self.__port.close()
                self.__port = None
                return
        else:
            logger.info("cannot perform __write() when unconnected")

    async def __read(self, end_marker=ELM_PROMPT):
        """Low-level read function.

        accumulates characters until the end marker (by
        default, the prompt character) is seen
        returns a list of [/r/n] delimited strings
        """
        if not self.__port:
            logger.info("cannot perform __read() when unconnected")
            return []

        buffer = bytearray()

        while True:
            # retrieve as much data as possible
            try:
                data = await self.__port.read(self.__port.in_waiting or 1)
            except Exception:
                self.__status = OBDStatus.NOT_CONNECTED
                await self.__port.close()
                self.__port = None
                logger.critical("Device disconnected while reading")
                return []

            # if nothing was received
            if not data:
                logger.warning("Failed to read port")
                break

            buffer.extend(data)

            # end on specified end-marker sequence
            if end_marker in buffer:
                break

        # log, and remove the "bytearray(   ...   )" part
        logger.debug("read: " + repr(buffer)[10:-1])

        # clean out any null characters
        buffer = re.sub(b"\x00", b"", buffer)

        # remove the prompt character
        if buffer.endswith(self.ELM_PROMPT):
            buffer = buffer[:-1]

        # convert bytes into a standard string
        string = buffer.decode("utf-8", "ignore")

        # splits into lines while removing empty lines and trailing spaces
        lines = [s.strip() for s in re.split("[\r\n]", string) if bool(s)]

        return lines
