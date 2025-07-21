"""Coodinator for Nissan Leaf OBD BLE."""

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.bluetooth.api import async_address_present
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NissanLeafObdBleApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# when the device is in range, and the car is on, poll quickly to get
# as much data as we can before it turns off
FAST_POLL_INTERVAL = timedelta(seconds=10)

# when the device is in range, but the car is off, we need to poll
# occasionally to see whether the car has be turned back on. On some cars
# this causes a relay to click every time, so this interval needs to be
# as long as possible to prevent excessive wear on the relay.
SLOW_POLL_INTERVAL = timedelta(minutes=5)

# when the device is out of range, use ultra slow polling since a bluetooth
# advertisement message will kick it back into life when back in range.
# see __init__.py: _async_specific_device_found()
ULTRA_SLOW_POLL_INTERVAL = timedelta(hours=1)


class NissanLeafObdBleDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, address: str, api: NissanLeafObdBleApiClient, options
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=FAST_POLL_INTERVAL,
            always_update=True,
        )
        self._address = address
        self.api = api
        self._cache_data: dict[str, Any] = {}
        self.cache_data = {}
        self.options = options

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""

        # Check if the device is still available
        _LOGGER.debug("Check if the device is still available to connect")
        available = async_address_present(self.hass, self._address, connectable=True)
        if not available:
            # Device out of range? Switch to active polling interval for when it reappears
            _LOGGER.debug("Car out of range? Switch to extra slow polling")
            self.update_interval = timedelta(seconds=self._xs_poll_interval)
            _LOGGER.debug(
                "Car out of range? Switch to ultra slow polling: interval = %s",
                self.update_interval,
            )
            if self.options["cache_values"]:
                return self._cache_data
            return {}

        try:
            new_data = await self.api.async_get_data()
            if len(new_data) == 0:
                # Car is probably off. Switch to slow polling inteval
                self.update_interval = timedelta(seconds=self._slow_poll_interval)
                _LOGGER.debug(
                    "Car is probably off, switch to slow polling: interval = %s",
                    self.update_interval,
                )
            else:
                self.update_interval = timedelta(seconds=self._fast_poll_interval)
                _LOGGER.debug(
                    "Car is on, polling: interval = %s",
                    self.update_interval,
                )
        except Exception as err:
            raise UpdateFailed(f"Unable to fetch data: {err}") from err
        else:
            if self.options["cache_values"]:
                self.cache_data.update(new_data)
                return self.cache_data
            return new_data

    @property
    def options(self):
        """User configuration options."""
        return self._options

    @options.setter
    def options(self, options):
        """Set the configuration options."""
        defaults = {
            "cache_values": False,
            "fast_poll": int(FAST_POLL_INTERVAL.total_seconds()),
            "slow_poll": int(SLOW_POLL_INTERVAL.total_seconds()),
            "xs_poll": int(ULTRA_SLOW_POLL_INTERVAL.total_seconds()),
        }
        self._options = {**defaults, **(options or {})}
        self._fast_poll_interval = self._options["fast_poll"]
        self._slow_poll_interval = self._options["slow_poll"]
        self._xs_poll_interval = self._options["xs_poll"]
