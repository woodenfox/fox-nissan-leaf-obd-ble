# Fox Nissan Leaf OBD BLE

A Home Assistant custom integration that communicates with a Nissan Leaf via an OBD-II Bluetooth Low Energy adapter. It exposes a number of sensors and binary sensors that report real time vehicle status such as state of charge, battery health, tyre pressures and more.

## Features
* Monitors 12V battery voltage and current
* Reports traction motor power, motor RPM and speed
* Provides tyre pressure and odometer readings
* Tracks charge statistics and range remaining
* Binary sensors for AC status, eco modes and other vehicle functions

## Installation
1. Copy the `custom_components/nissan_leaf_obd_ble` directory into the `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.
3. In the Home Assistant UI open **Settings > Devices & Services** and add the **Nissan Leaf OBD BLE** integration. Provide the Bluetooth address of your OBD BLE adapter when prompted.

Alternatively, if you use HACS, add this repository as a custom repository and install the integration from the HACS store.

## Configuration
After installation you can adjust polling intervals and other options from the integration's configuration page.

## Development
This project is maintained in the `fox-nissan-leaf-obd-ble` repository. Contributions and issue reports are welcome.
