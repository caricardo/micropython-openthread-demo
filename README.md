# MicroPython OpenThread for ESP32-C6

[![MicroPython](https://img.shields.io/badge/MicroPython-ESP32--C6-2b2728)](https://micropython.org/)
[![OpenThread](https://img.shields.io/badge/OpenThread-IPv6%20mesh-00a98f)](https://openthread.io/)
[![IEEE 802.15.4](https://img.shields.io/badge/radio-IEEE%20802.15.4-4c6ef5)](https://www.espressif.com/en/products/socs/esp32-c6)
[![GitHub release](https://img.shields.io/github/v/release/caricardo/micropython-openthread-demo?include_prereleases)](https://github.com/caricardo/micropython-openthread-demo/releases)

Custom MicroPython firmware and reference application for **ESP32-C6** using the native **IEEE 802.15.4** radio to join an **OpenThread** mesh. The demo includes **Thread IPv6**, **SRP/DNS-SD service registration**, **mDNS discovery through an OpenThread Border Router (OTBR)**, **IPv6 WebREPL**, browser-based Wi-Fi provisioning for the Thread Active Dataset, an SRP recovery watchdog, and an HTTP RGB LED service.

> Status: proof of concept. This is not an official MicroPython, Espressif, or OpenThread distribution.

## Features

- Native ESP32-C6 IEEE 802.15.4 radio
- Router-eligible, non-sleepy Thread device
- IPv6 sockets over the Thread interface
- Unique EUI-64-based device and service names
- SRP client registration and DNS-SD/mDNS discovery through OTBR
- IPv6 WebREPL on TCP port 8266
- Temporary Wi-Fi access point for first-boot Thread dataset provisioning
- SRP watchdog that recovers stale client registrations
- Optional boot-time GPIO factory reset for OpenThread persistent settings
- HTTP RGB LED demo on TCP port 80
- Prebuilt merged firmware image and source-build instructions

## Tested setup

- Board: [WeAct ESP32-C6-MiNi](https://github.com/WeActStudio/WeActStudio.ESP32C6-MINI)
- Border router hardware: SMLIGHT SLZB-07MG24
- Border router software: OpenThread Border Router
- Radio: native ESP32-C6 IEEE 802.15.4
- Client systems: Linux and Windows
- RGB LED: onboard NeoPixel on GPIO8

Other ESP32-C6 boards and OTBR implementations may work, but have not all been tested.

## Repository layout

```text
.
├── README.md
├── boot.py
├── app.py
└── firmware/
    └── ESP32_GENERIC_C6_OT.bin
```

- `boot.py` initializes OpenThread, provisions the dataset when missing, configures SRP and IPv6 WebREPL, starts the SRP watchdog, and optionally runs `app.py`.
- `app.py` registers a unique `_http._tcp` service and starts the RGB HTTP server.
- `firmware/ESP32_GENERIC_C6_OT.bin` is a merged image containing the bootloader, partition table, and MicroPython firmware.

## Requirements

Install:

- Python 3
- `mpremote`
- `esptool`

Find the serial port:

```bash
ls /dev/ttyACM*
```

The commands below use `/dev/ttyACM0`.

## Quick start

### 1. Erase and flash the firmware

```bash
esptool.py --chip esp32c6 -p /dev/ttyACM0 erase_flash

esptool.py --chip esp32c6 -p /dev/ttyACM0 -b 460800 \
    write_flash -z 0x0 firmware/ESP32_GENERIC_C6_OT.bin
```

### 2. Upload the runtime scripts

```bash
mpremote connect /dev/ttyACM0 fs cp app.py :app.py
mpremote connect /dev/ttyACM0 fs cp boot.py :boot.py
mpremote connect /dev/ttyACM0 reset
```

### 3. Provision the Thread Active Dataset

When no valid dataset exists, `boot.py` starts a temporary Wi-Fi access point.

Default settings:

```text
SSID:     esp32c6-<device-eui64>-thread-setup
Password: threadsetup
URL:      http://192.168.4.1/
```

Connect to the access point, open the URL, paste the hexadecimal Thread Active Dataset TLVs, and submit the form. The board stores the dataset in OpenThread persistent settings and reboots.

Export the Active Dataset from an OTBR container:

```bash
docker exec otbr ot-ctl dataset active -x
```

Do not publish a real Thread dataset. It contains network credentials.

## Expected boot output

```text
uid: 0123456789abcdef
model: esp32c6
host: esp32c6-0123456789abcdef
thread dataset: configured
thread default netif: ok
srp lease: {'srp_key_lease': 1800, 'srp_lease': 300, 'srp_ttl': 300}
srp host: esp32c6-0123456789abcdef
srp service: esp32c6-0123456789abcdef-webrepl._webrepl._tcp
thread state: child
webrepl6: ws://esp32c6-0123456789abcdef.local:8266/
app thread: started app.py
http srp service: esp32-rgb-0123456789abcdef._http._tcp
rgb http: http://[::]:80/
srp watchdog: started
```

The Thread role may become `child`, `router`, or `leader`.

## OpenThread diagnostics from MicroPython

```python
import openthread

print(openthread.version())
print(openthread.state())
print(openthread.status())
print(openthread.ipaddr())
print(openthread.diagnostics())
print(openthread.srp_client())
print(openthread.srp_client_events(clear=False))
```

Runtime helpers exposed by `boot.py`:

```python
print(threads())
print(srp_watchdog_status())
```

## Verify SRP and mDNS discovery

On the OTBR host:

```bash
docker exec otbr ot-ctl srp server host
docker exec otbr ot-ctl srp server service
```

Expected service names are unique per board:

```text
esp32c6-<eui64>-webrepl._webrepl._tcp.default.service.arpa.
esp32-rgb-<eui64>._http._tcp.default.service.arpa.
```

Browse the services from Linux with Avahi:

```bash
avahi-browse --resolve --terminate _webrepl._tcp
avahi-browse --resolve --terminate _http._tcp
```

Resolve the board hostname:

```bash
avahi-resolve-host-name -6 esp32c6-<eui64>.local
```

## WebREPL over Thread IPv6

Open a WebREPL client and connect with either the mDNS hostname or an IPv6 literal:

```text
ws://esp32c6-<eui64>.local:8266/
ws://[fd00:1234:5678:1::32]:8266/
```

Default demo password:

```text
1234
```

Change `WEBREPL_PASSWORD` before using the device on a real network.

## HTTP RGB demo

Open the service with the mDNS hostname:

```text
http://esp32c6-<eui64>.local/
```

Or use the IPv6 address directly:

```bash
curl -g -6 'http://[fd00:1234:5678:1::32]/status'
```

Endpoints:

```text
GET /                 RGB control page
GET /status           Current color
GET /set?hex=rrggbb    Set a color
GET /off              Turn the LED off
GET /test             Run a short RGB test
```

## Optional GPIO factory reset

The factory-reset input is disabled by default:

```python
FACTORY_RESET_ENABLED = False
FACTORY_RESET_SENSE_PIN = 4
FACTORY_RESET_DRIVE_PIN = None
FACTORY_RESET_HOLD_MS = 3000
```

When enabled, short the configured sense pin to GND while the board boots and hold it for the configured duration. This erases the Thread dataset, SRP key, and other OpenThread persistent settings. It does not erase `boot.py`, `app.py`, or the MicroPython filesystem.

## Build the firmware from source

The firmware is built from the MicroPython fork and branch below:

```bash
git clone https://github.com/caricardo/micropython.git
cd micropython
git checkout dev/esp32-openthread
git submodule update --init --recursive
```

Activate ESP-IDF 5.5.2:

```bash
. ~/.espressif/tools/activate_idf_v5.5.2.sh
export PATH="$IDF_PATH/tools:$PATH"
hash -r
```

Build and deploy:

```bash
cd ports/esp32
make BOARD=ESP32_GENERIC_C6_OT
make BOARD=ESP32_GENERIC_C6_OT PORT=/dev/ttyACM0 deploy
```

### Build `mpy-cross` with the host compiler

If ESP-IDF toolchain variables leak into the host build:

```bash
cd micropython

env -u CC -u CXX -u AS -u AR -u LD \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    make -C mpy-cross clean

env -u CC -u CXX -u AS -u AR -u LD \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    make -C mpy-cross
```

Then rebuild the ESP32-C6 target.

## Create a merged firmware image

From `micropython/ports/esp32`:

```bash
python -m esptool --chip esp32c6 merge_bin \
    -o ESP32_GENERIC_C6_OT.bin \
    --flash_mode dio \
    --flash_size 4MB \
    --flash_freq 80m \
    0x0 build-ESP32_GENERIC_C6_OT/bootloader/bootloader.bin \
    0x8000 build-ESP32_GENERIC_C6_OT/partition_table/partition-table.bin \
    0x10000 build-ESP32_GENERIC_C6_OT/micropython.bin
```

## Security and limitations

- Change the default WebREPL and provisioning passwords.
- Keep Thread Active Dataset credentials private.
- The included firmware and scripts are a proof of concept and have not undergone a production security review.
- SRP lease values in `boot.py` must match the OTBR server policy shown by `ot-ctl srp server lease`.
- The optional factory reset erases the SRP key; old names may remain reserved on the SRP server until the key lease expires.
- The demo runs as an always-on, router-eligible Thread device and is not optimized for battery operation.

## Related source

OpenThread module and firmware development:

- [caricardo/micropython](https://github.com/caricardo/micropython)
- Branch: `dev/esp32-openthread`

Parts of this repository and related MicroPython work were prepared with AI assistance, then built and tested on real ESP32-C6 and OTBR hardware.

## License

The original files in this repository are licensed under the MIT License.

The prebuilt firmware contains third-party components, including MicroPython,
ESP-IDF, and OpenThread, which remain subject to their respective licenses.
See [LICENSE](LICENSE).
