"""Module to implement a serial-like interface over BLE GATT."""

import asyncio
import logging

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class bleserial:
    """Encapsulates the ble connection and make it appear something like a UART port."""

    __buffer = bytearray()

    def __init__(
        self,
        device: BLEDevice,
        service_uuid,
        characteristic_uuid_read,
        characteristic_uuid_write,
    ) -> None:
        """Initialise."""
        self.device = device
        self.service_uuid = service_uuid
        self.characteristic_uuid_read = characteristic_uuid_read
        self.characteristic_uuid_write = characteristic_uuid_write
        self.client = None
        self._rx_buffer = bytearray()
        self._timeout = None
        self._write_timeout = None
        self._notifications_started = False
        self._read_char = None
        self._write_char = None

    async def _wait_for_data(self, size):
        while len(self._rx_buffer) < size:
            await asyncio.sleep(0.01)

    async def _wait_for_line(self):
        while b"\n" not in self._rx_buffer:
            await asyncio.sleep(0.01)

    def reset_input_buffer(self):
        """Reset the input buffer."""
        logger.debug("Resetting input buffer")
        self._rx_buffer.clear()

    def reset_output_buffer(self):
        """Reset the output buffer."""
        logger.debug("Resetting output buffer")
        # Since there's no explicit output buffer, this is a no-op.

    def flush(self):
        """Reset the input and the output buffer."""
        self.reset_input_buffer()
        self.reset_output_buffer()

    @property
    def in_waiting(self):
        """Return the number of bytes in the receive buffer."""
        return len(self._rx_buffer)

    @property
    def timeout(self):
        """Timeout duration."""
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        """Set the timeout duration."""
        self._timeout = value

    @property
    def write_timeout(self):
        """Write timeout duration."""
        return self._write_timeout

    @write_timeout.setter
    def write_timeout(self, value):
        """Set the write timeout duration."""
        self._write_timeout = value

    def _notification_handler(self, sender, data):
        """Handle when a GATT notification arrives."""
        logger.debug("Notification received: %s", data)
        self._rx_buffer.extend(data)

    async def open(self):
        """Open the port."""
        self.client = BleakClient(self.device)
        try:
            logger.debug("Connecting to device: %s", self.device)
            await self.client.connect()
            logger.debug("Connected to device: %s", self.device)

            services = await self.client.get_services()
            service = services.get_service(self.service_uuid)
            read_char = None
            write_char = None
            if service:
                for char in service.characteristics:
                    if (
                        self.characteristic_uuid_read.lower() == char.uuid.lower()
                        and read_char is None
                    ):
                        read_char = char
                    if (
                        self.characteristic_uuid_write.lower() == char.uuid.lower()
                        and write_char is None
                    ):
                        write_char = char
            if read_char is None or write_char is None:
                raise BleakError("Unable to locate GATT characteristics")

            logger.debug(
                "Starting notifications on characteristic UUID: %s",
                self.characteristic_uuid_read,
            )
            await self.client.start_notify(read_char.handle, self._notification_handler)
            self._read_char = read_char
            self._write_char = write_char
            self._notifications_started = True
            logger.debug("Notifications started")
        except BleakError as e:
            logger.error("Failed to connect or start notifications: %s", e)
            raise

    async def close(self):
        """Close the port."""
        if self.client:
            if self.client.is_connected:
                try:
                    if self._notifications_started and self._read_char is not None:
                        logger.debug(
                            "Stopping notifications on characteristic UUID: %s",
                            self.characteristic_uuid_read,
                        )
                        await self.client.stop_notify(self._read_char.handle)
                        logger.debug("Notifications stopped")
                    logger.debug("Disconnecting from device")
                    await self.client.disconnect()
                    logger.debug("Disconnected from device")
                except BleakError as e:
                    logger.warning("Failed to stop notifications or disconnect: %s", e)
            else:
                logger.debug("Client already disconnected")
            self.client = None

    async def write(self, data):
        """Write bytes."""
        if isinstance(data, str):
            data = data.encode()
        try:
            logger.info(
                "Writing data to characteristic UUID: %s Data: %s",
                self.characteristic_uuid_write,
                data,
            )
            await self.client.write_gatt_char(self._write_char.handle, data)
            logger.debug("Data written")
        except BleakError as e:
            logger.error("Failed to write data: %s", e)
            raise

    async def read(self, size=1):
        """Read from the buffer."""
        try:
            logger.debug("Reading %s bytes of data", size)
            while len(self._rx_buffer) < size:
                await asyncio.sleep(0.01)
            data = self._rx_buffer[:size]
            self._rx_buffer = self._rx_buffer[size:]
            logger.debug("Read data: %s", data)
            return bytes(data)
        except Exception as e:
            logger.error("Failed to read data: %s", e)
            raise

    async def readline(self):
        """Read a whole line from the buffer."""
        try:
            logger.debug("Reading line")
            await asyncio.wait_for(self._wait_for_line(), timeout=self._timeout)
            index = self._rx_buffer.index(b"\n") + 1
            data = self._rx_buffer[:index]
            self._rx_buffer = self._rx_buffer[index:]
            logger.debug("Read line: %s", data)
            return bytes(data)
        except TimeoutError as e:
            logger.error("Readline operation timed out")
            raise BleakError("Readline operation timed out") from e
        except Exception as e:
            logger.error("Failed to read line: %s", e)
            raise
