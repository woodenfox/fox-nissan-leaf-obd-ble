import importlib.util
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath("."))

# Provide minimal bleak module so that the modules under test can be imported
bleak = types.ModuleType("bleak")
backends = types.ModuleType("bleak.backends")
device_mod = types.ModuleType("bleak.backends.device")

class BLEDevice:  # dummy stand-in
    pass

device_mod.BLEDevice = BLEDevice
class BleakClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class BleakError(Exception):
    pass

bleak.BleakClient = BleakClient
bleak.BleakError = BleakError
backends.device = device_mod
bleak.backends = backends
sys.modules.setdefault("bleak", bleak)
sys.modules.setdefault("bleak.backends", backends)
sys.modules.setdefault("bleak.backends.device", device_mod)

# Stub package for custom_components.nissan_leaf_obd_ble to avoid executing its
# heavy __init__ when importing submodules.
cc_pkg = types.ModuleType("custom_components")
leaf_pkg = types.ModuleType("custom_components.nissan_leaf_obd_ble")
pkg_path = os.path.join("custom_components", "nissan_leaf_obd_ble")
leaf_pkg.__path__ = [pkg_path]
sys.modules.setdefault("custom_components", cc_pkg)
sys.modules.setdefault("custom_components.nissan_leaf_obd_ble", leaf_pkg)

def _load_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[module_name] = module
    return module

obd_module = _load_module(
    "custom_components.nissan_leaf_obd_ble.obd", os.path.join(pkg_path, "obd.py")
)
command_module = _load_module(
    "custom_components.nissan_leaf_obd_ble.OBDCommand", os.path.join(pkg_path, "OBDCommand.py")
)
elm327_module = _load_module(
    "custom_components.nissan_leaf_obd_ble.elm327", os.path.join(pkg_path, "elm327.py")
)

leaf_pkg.obd = obd_module
leaf_pkg.OBDCommand = command_module
leaf_pkg.elm327 = elm327_module

OBD = obd_module.OBD
OBDCommand = command_module.OBDCommand
OBDStatus = elm327_module.OBDStatus


class DummyFrame:
    def __init__(self, raw: str) -> None:
        self.raw = raw


class DummyMessage:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.data = bytearray()
        self.frames = [DummyFrame(raw)]


def make_obd(messages):
    obd = OBD(None)

    class DummyInterface:
        def status(self):
            return OBDStatus.CAR_CONNECTED

        async def send_and_parse(self, cmd):
            return messages

    obd.interface = DummyInterface()

    async def noop(*args, **kwargs):
        return None

    obd._OBD__set_header = noop
    obd.test_cmd = lambda cmd: True
    return obd


def make_cmd():
    return OBDCommand("dummy", "dummy", b"00", 0, lambda m: "decoded", header=b"00")


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["NO DATA", "CAN ERROR"])
async def test_query_vehicle_not_responding(raw):
    msg = DummyMessage(raw)
    obd = make_obd([msg])
    cmd = make_cmd()
    response = await obd.query(cmd, force=True)
    assert response.messages == []
    assert response.value is None
