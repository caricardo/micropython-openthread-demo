# MicroPython OpenThread Demo for ESP32-C6

Proof-of-concept MicroPython OpenThread demo for ESP32-C6.

It demonstrates:

* Thread IPv6 connectivity
* SRP service registration
* IPv6 WebREPL
* HTTP RGB LED control over Thread

## Tested setup

* ESP32-C6 board: [WeAct ESP32-C6-MiNi](https://github.com/WeActStudio/WeActStudio.ESP32C6-MINI)
* Radio: native ESP32-C6 IEEE 802.15.4
* OpenThread Border Router: SMLIGHT SLZB-07MG24
* Thread network devices: only the SMLIGHT SLZB-07MG24 border router and this ESP32-C6 board were used during testing
* ESP32-C6 mode: active, non-sleepy Thread device
* Client systems: Linux and Windows
* RGB LED: onboard LED on GPIO8

## Repository contents

```text
.
├── README.md
├── boot.py
├── app.py
└── firmware/
    └── ESP32_GENERIC_C6_OT.bin
```

`boot.py` starts OpenThread, sets the Thread interface as the lwIP default route,
registers WebREPL with SRP, starts IPv6 WebREPL, and optionally starts `app.py`.

`app.py` starts a small HTTP RGB LED server over Thread IPv6.

## Requirements

* mpremote
* esptool

Connect the board and check the serial port:

```bash
ls /dev/ttyACM*
```

The examples below use `/dev/ttyACM0`. Change the port if your board appears
under a different device name.

## Flash firmware

Erase flash:

```bash
esptool.py --chip esp32c6 -p /dev/ttyACM0 erase_flash
```

Flash the prebuilt merged firmware image:

```bash
esptool.py --chip esp32c6 -p /dev/ttyACM0 -b 460800 write_flash -z 0x0 firmware/ESP32_GENERIC_C6_OT.bin
```

Open REPL:

```bash
mpremote connect /dev/ttyACM0 repl
```

## Upload demo files

Copy `boot.py` and `app.py` to the board:

```bash
mpremote connect /dev/ttyACM0 fs cp app.py :app.py
mpremote connect /dev/ttyACM0 fs cp boot.py :boot.py
```

Reset:

```bash
mpremote connect /dev/ttyACM0 reset
```

## Configure Thread dataset

The board needs a valid Thread Active Dataset before it can join your Thread
network.

Export the active dataset from OTBR:

```bash
docker exec otbr ot-ctl dataset active -x
```

Copy the dataset hex string, then paste it in the MicroPython REPL:

```python
import openthread
import machine

openthread.init()
openthread.stop()

openthread.dataset_set("<paste dataset hex here>")

machine.reset()
```

Example shape:

```python
openthread.dataset_set("0e080000000000010000000300001234...")
```

Do not commit or publish a real Thread dataset. It contains network credentials.

## Expected boot log

After reset, the log should show Thread attach, SRP registration, DNS setup,
WebREPL startup, and the RGB HTTP demo:

```text
uid: ...
model: esp32c6
host: esp32c6-...
thread default netif: ok
thread state: detached
thread state: child
srp lease: {'srp_key_lease': 1800, 'srp_lease': 300, 'srp_ttl': 300}
srp host: esp32c6-...
webrepl6: ws://esp32c6-....local:8266/
app thread: started app.py
rgb http: http://[::]:80/
```

## Check OpenThread from REPL

```python
import openthread

print(openthread.version())
print(openthread.state())
print(openthread.ipaddr())
print(openthread.srp_client())
```

Expected version:

```text
micropython-openthread 0.0.1
```

The Thread role should eventually become:

```text
child
```

or, depending on configuration:

```text
router
leader
```

## Check SRP registration on OTBR

On the OTBR host:

```bash
docker exec -it otbr ot-ctl srp server host
docker exec -it otbr ot-ctl srp server service
```

Expected example:

```text
esp32c6-....default.service.arpa.
    addresses: [fd00:1234:5678:1::32]

esp32-webrepl._webrepl._tcp.default.service.arpa.
    port: 8266

esp32-rgb._http._tcp.default.service.arpa.
    port: 80
```

## WebREPL over Thread IPv6

Start a local WebREPL web client from a directory containing `webrepl.html`:

```bash
python3 -m http.server 8080 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:8080/webrepl.html
```

Use the WebSocket URL printed by `boot.py`, or use the Thread IPv6 address:

```text
ws://[fd00:1234:5678:1::32]:8266/
```

The WebREPL client was tested from Linux and Windows browsers. Use the IPv6
literal form if local hostname resolution is not available on the client.

Default demo password:

```text
1234
```

Change `WEBREPL_PASSWORD` in `boot.py` before using this on a real network.

## HTTP RGB demo

`app.py` starts an HTTP server on port `80`.

Use the IPv6 address from `openthread.ipaddr()` or OTBR SRP output.

Linux:

```bash
curl -g 'http://[fd00:1234:5678:1::32]/'
```

Windows PowerShell:

```powershell
curl.exe 'http://[fd00:1234:5678:1::32]/'
```

A browser can also open the same IPv6 literal URL:

```text
http://[fd00:1234:5678:1::32]/
```

Available paths:

```text
/
/red
/green
/blue
/magenta
/white
/off
```

## Build firmware from source

The prebuilt firmware was produced from the MicroPython fork at
[caricardo/micropython](https://github.com/caricardo/micropython), branch
`dev/esp32-openthread`.

Clone the fork and switch to the OpenThread development branch:

```bash
git clone https://github.com/caricardo/micropython.git
cd micropython
git checkout dev/esp32-openthread
git submodule update --init --recursive
```

Activate ESP-IDF first:

```bash
. ~/.espressif/tools/activate_idf_v5.5.2.sh
export PATH="$IDF_PATH/tools:$PATH"
hash -r
```

Build:

```bash
cd ports/esp32
make BOARD=ESP32_GENERIC_C6_OT
```

Flash from the source tree:

```bash
make BOARD=ESP32_GENERIC_C6_OT \
    PORT=/dev/ttyACM0 \
    deploy
```

Open REPL:

```bash
mpremote connect /dev/ttyACM0 repl
```

## Create a merged firmware image

Run this from `micropython/ports/esp32`:

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

The merged image can then be flashed with the command from the `Flash firmware`
section:

```bash
# NVS will be erased.
esptool.py --chip esp32c6 -p /dev/ttyACM0 -b 460800 write_flash -z 0x0 firmware/ESP32_GENERIC_C6_OT.bin
```

## Fix mpy-cross build issues

If the build fails while building `mpy-cross`, the ESP-IDF environment may have
leaked cross-compiler variables or toolchain paths into the host build.

`mpy-cross` is a host tool, so it must be built with the normal system compiler,
not with the ESP32/RISC-V toolchain.

From the MicroPython repository root:

```bash
cd micropython

env -u CC -u CXX -u AS -u AR -u LD \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    make -C mpy-cross clean

env -u CC -u CXX -u AS -u AR -u LD \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    make -C mpy-cross
```

Then build the ESP32-C6 firmware again:

```bash
cd ports/esp32
make BOARD=ESP32_GENERIC_C6_OT
```

## Notes

This is a proof-of-concept demo.

Parts of this repository and the related MicroPython / micropython-lib work were
prepared with AI assistance, then built and tested on real ESP32-C6 and OTBR
hardware.

This repository contains demo files, usage notes, and optionally prebuilt
firmware.

Firmware and OpenThread module development lives in the MicroPython fork:
[caricardo/micropython](https://github.com/caricardo/micropython), branch
`dev/esp32-openthread`.
