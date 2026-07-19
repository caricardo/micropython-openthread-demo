# /flash/boot.py

import time
import os
import machine


WEBREPL_PASSWORD = "1234"
WEBREPL_PORT = 8266

SRP_SERVICE_TYPE = "_webrepl._tcp"

# Match the confirmed OTBR SRP Server policy:
# min/max lease 30/300, min/max key-lease 30/1800.
# Thread Network Data publishes the SRP endpoint, not this lease policy, so
# these values must be kept aligned with `ot-ctl srp server lease`.
SRP_LEASE = 300
SRP_KEY_LEASE = 1800
SRP_TTL = 300

# Recover from a stale local Registered state after the SRP Server loses its
# volatile registration database. A normal successful refresh is expected well
# before the lease expires; restart the client if no success is observed for
# 30 seconds less than the configured lease.
SRP_WATCHDOG_ENABLED = True
SRP_WATCHDOG_POLL_MS = 10000
SRP_WATCHDOG_STALE_MS = (SRP_LEASE - 30) * 1000
SRP_WATCHDOG_UNREGISTERED_MS = 60000
SRP_WATCHDOG_RESTART_DELAY_MS = 500

# Optional boot-time Thread factory reset input. Disabled by default.
#
# With FACTORY_RESET_DRIVE_PIN = None, connect FACTORY_RESET_SENSE_PIN
# to GND and hold it while the board boots. To use two isolated GPIO pads,
# set FACTORY_RESET_DRIVE_PIN to a second GPIO and short the two pads.
# The reset erases OpenThread persistent data, including the active dataset
# and SRP key. boot.py/app.py and the rest of the filesystem are preserved.
FACTORY_RESET_ENABLED = False
FACTORY_RESET_SENSE_PIN = 4
FACTORY_RESET_DRIVE_PIN = None
FACTORY_RESET_ACTIVE_LEVEL = 0
FACTORY_RESET_HOLD_MS = 3000
FACTORY_RESET_SAMPLE_MS = 25
FACTORY_RESET_RELEASE_STABLE_MS = 500

APP_AUTOSTART = True
# Use app.py or main.py for user code, not simultaneously.
APP_FILE = "app.py"

# Thread dataset provisioning over a temporary Wi-Fi access point.
PROVISION_AP_PASSWORD = "threadsetup"
PROVISION_AP_CHANNEL = 6
PROVISION_HTTP_PORT = 80
PROVISION_AP_ADDR = "192.168.4.1"
PROVISION_MAX_REQUEST = 4096

# ESP-IDF can generate this development fallback dataset after Thread is
# started without a configured dataset. Check the dataset before start(), and
# optionally treat this known fallback as unconfigured if it was persisted by
# an older boot.py.
PROVISION_IGNORE_ESP_IDF_FALLBACK = True
ESP_IDF_FALLBACK_DATASET = (
    "0e080000000000000000000300000b4a0300000b35060004001fffe0"
    "0208dead00beef00cafe0708fddead00beef000005103d3a5519b15a"
    "3f72f7880d6673ccce07030a4f70656e546872656164010206e80410"
    "3ea58ec9aadde7b6fb3b2032457070c40c0402a0f7f8"
)


def dns_label(text):
    text = text.lower()
    out = []

    for ch in text:
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            out.append(ch)
        elif ch in ("-", "_", " ", ".", "/"):
            out.append("-")

    label = "".join(out).strip("-")

    while "--" in label:
        label = label.replace("--", "-")

    return label or "esp32"


def get_mcu_model():
    try:
        s = os.uname().machine.lower()
    except Exception:
        return "esp32"

    if "with " in s:
        s = s.split("with ", 1)[1]

    s = s.replace("-", "").replace(" ", "")

    if "esp32c6" in s:
        return "esp32c6"
    if "esp32c3" in s:
        return "esp32c3"
    if "esp32s3" in s:
        return "esp32s3"
    if "esp32s2" in s:
        return "esp32s2"
    if "esp32" in s:
        return "esp32"

    return dns_label(s)


def get_host_name():
    uid = machine.unique_id().hex().lower()
    return "{}-{}".format(get_mcu_model(), uid)


def factory_reset_contact_active(pin):
    return pin.value() == FACTORY_RESET_ACTIVE_LEVEL


def factory_reset_pull():
    if FACTORY_RESET_ACTIVE_LEVEL == 0:
        return machine.Pin.PULL_UP
    if FACTORY_RESET_ACTIVE_LEVEL == 1:
        return machine.Pin.PULL_DOWN
    raise ValueError("factory reset active level must be 0 or 1")


def release_factory_reset_pins(sense_pin, drive_pin):
    try:
        sense_pin.init(machine.Pin.IN, factory_reset_pull())
    except Exception:
        pass

    if drive_pin is not None:
        try:
            drive_pin.init(machine.Pin.IN)
        except Exception:
            pass


def wait_factory_reset_release(sense_pin):
    stable_since = None

    while True:
        now = time.ticks_ms()

        if factory_reset_contact_active(sense_pin):
            stable_since = None
        elif stable_since is None:
            stable_since = now
        elif time.ticks_diff(now, stable_since) >= FACTORY_RESET_RELEASE_STABLE_MS:
            return

        time.sleep_ms(FACTORY_RESET_SAMPLE_MS)


def check_factory_reset(openthread):
    if not FACTORY_RESET_ENABLED:
        return False

    sense_pin = None
    drive_pin = None

    try:
        if (
            FACTORY_RESET_DRIVE_PIN is not None
            and FACTORY_RESET_DRIVE_PIN == FACTORY_RESET_SENSE_PIN
        ):
            raise ValueError("factory reset pins must be different")

        sense_pin = machine.Pin(
            FACTORY_RESET_SENSE_PIN,
            machine.Pin.IN,
            factory_reset_pull(),
        )

        if FACTORY_RESET_DRIVE_PIN is not None:
            drive_pin = machine.Pin(
                FACTORY_RESET_DRIVE_PIN,
                machine.Pin.OUT,
                value=0 if FACTORY_RESET_ACTIVE_LEVEL == 0 else 1,
            )

        if not factory_reset_contact_active(sense_pin):
            return False

        print(
            "factory reset: contact detected; hold for {} ms".format(
                FACTORY_RESET_HOLD_MS,
            )
        )

        deadline = time.ticks_add(time.ticks_ms(), FACTORY_RESET_HOLD_MS)

        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if not factory_reset_contact_active(sense_pin):
                print("factory reset: cancelled")
                return False

            time.sleep_ms(FACTORY_RESET_SAMPLE_MS)

        print("factory reset: erasing OpenThread persistent data")
        openthread.erase_persistent()
        print("factory reset: complete; release reset contacts")

        wait_factory_reset_release(sense_pin)
        release_factory_reset_pins(sense_pin, drive_pin)
        time.sleep_ms(250)
        machine.reset()
        return True

    except Exception as exc:
        print("factory reset check failed:", exc)
        return False

    finally:
        # Keep both pads high-impedance after a cancelled or failed check.
        if sense_pin is not None:
            release_factory_reset_pins(sense_pin, drive_pin)


_thread_registry = {}
_thread_registry_lock = None


def init_thread_registry():
    global _thread_registry_lock

    if _thread_registry_lock is None:
        import _thread
        _thread_registry_lock = _thread.allocate_lock()


def set_thread_state(name, state=None, thread_id=None, error=None):
    init_thread_registry()
    _thread_registry_lock.acquire()

    try:
        entry = _thread_registry.get(name, {})
        entry["name"] = name
        entry["updated_ms"] = time.ticks_ms()

        if state is not None:
            entry["state"] = state
        if thread_id is not None:
            entry["id"] = thread_id
        if error is not None:
            entry["error"] = str(error)

        _thread_registry[name] = entry
    finally:
        _thread_registry_lock.release()


def thread_heartbeat(name):
    set_thread_state(name, "running")


def threads():
    init_thread_registry()
    _thread_registry_lock.acquire()

    try:
        result = {}
        for name, entry in _thread_registry.items():
            result[name] = dict(entry)
        return result
    finally:
        _thread_registry_lock.release()


def tracked_thread_worker(name, target, args):
    import _thread

    thread_id = _thread.get_ident()
    set_thread_state(name, "running", thread_id)

    try:
        target(*args)
        set_thread_state(name, "finished", thread_id)
    except Exception as exc:
        set_thread_state(name, "crashed", thread_id, exc)
        print("thread crashed:", name, exc)


def start_tracked_thread(name, target, args=()):
    import _thread

    set_thread_state(name, "starting")
    thread_id = _thread.start_new_thread(
        tracked_thread_worker,
        (name, target, args),
    )
    set_thread_state(name, thread_id=thread_id)
    return thread_id


def wait_thread_attached(openthread, timeout_s=60):
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        try:
            state = openthread.state()
        except Exception:
            state = None

        print("thread state:", state)

        if state in ("child", "router", "leader"):
            return True

        time.sleep(2)

    print("thread attach timeout")
    return False


def start_webrepl6(password=WEBREPL_PASSWORD, port=WEBREPL_PORT, host=None):
    import socket
    import webrepl
    import _webrepl
    import gc

    try:
        webrepl.stop()
    except Exception:
        pass

    gc.collect()

    _webrepl.password(password)

    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("::", port))
    s.listen(1)

    s.setsockopt(socket.SOL_SOCKET, socket.SO_EVENT_CALLBACK, webrepl.accept_conn)
    webrepl.listen_s = s

    if host:
        print("webrepl6: http://{}:{}/".format(host + ".local", port))
        print("webrepl6: ws://{}:{}/".format(host + ".local", port))

        # Some OpenWrt setups can also expose mDNS/SRP hostnames through
        # local DNS zones such as .lan or .local.lan.
        print("webrepl6: http://{}:{}/".format(host + ".lan", port))
        print("webrepl6: ws://{}:{}/".format(host + ".lan", port))
    else:
        print("webrepl6: http://<host>.local:{}/".format(port))
        print("webrepl6: ws://<host>.local:{}/".format(port))

    return s


def register_srp_webrepl(openthread, host):
    uid = machine.unique_id().hex().lower()
    model = get_mcu_model()
    service_instance = dns_label(host + "-webrepl")[:63]

    try:
        openthread.srp_client_clear()
    except Exception as exc:
        print("srp clear failed:", exc)

    try:
        print("srp lease:", openthread.srp_client_lease(SRP_LEASE, SRP_KEY_LEASE, SRP_TTL))
    except Exception as exc:
        print("srp lease config failed:", exc)

    openthread.srp_client_host(host)
    openthread.srp_client_host_address_auto()

    openthread.srp_client_add_service(
        service_instance,
        SRP_SERVICE_TYPE,
        WEBREPL_PORT,
        0,
        0,
        {
            "id": uid,
            "model": model,
            "fw": "micropython",
            "svc": "webrepl",
        },
    )

    openthread.srp_client_autostart(True)

    print("srp host:", host)
    print("srp service:", service_instance + "." + SRP_SERVICE_TYPE)
    print("expected local:", host + ".local")
    print("expected lan:", host + ".lan")


def run_app_file(path):
    # Run a Python file as a standalone script inside the current thread.
    # Missing app.py is not fatal: boot.py should still provide Thread and WebREPL.
    try:
        with open(path, "r") as f:
            code = f.read()
    except OSError:
        print("warning: optional app file not found:", path)
        return

    try:
        print("app: starting", path)

        g = {
            "__name__": "__main__",
            "__file__": path,
        }

        exec(code, g)

        print("app: finished", path)

    except Exception as exc:
        print("warning: app crashed:", exc)


def file_exists(path):
    try:
        f = open(path, "r")
        f.close()
        return True
    except OSError:
        return False


def start_app_thread(path=APP_FILE):
    if not file_exists(path):
        print("warning: optional app file not found:", path)
        return False

    try:
        thread_id = start_tracked_thread(
            "app",
            run_app_file,
            (path,),
        )
        print("app thread: started", path, thread_id)
        return True
    except Exception as exc:
        print("warning: app thread failed:", exc)
        return False



def get_wlan_interface_id(network, name):
    wlan_name = "IF_" + name

    try:
        return getattr(network.WLAN, wlan_name)
    except AttributeError:
        return getattr(network, name + "_IF")


def normalize_dataset_hex(value):
    value = value.strip()

    if value.startswith("0x") or value.startswith("0X"):
        value = value[2:]

    out = []

    for ch in value:
        if ch in " \t\r\n:-":
            continue
        out.append(ch.lower())

    value = "".join(out)

    if not value:
        raise ValueError("dataset is empty")

    if len(value) % 2:
        raise ValueError("dataset hex length must be even")

    # OpenThread operational dataset TLVs are limited by the C binding.
    if len(value) > 508:
        raise ValueError("dataset is too long")

    for ch in value:
        if ch not in "0123456789abcdef":
            raise ValueError("dataset must contain hexadecimal characters only")

    return value


def thread_dataset_get(openthread):
    # openthread.init() must be called before this helper. The check is made
    # before openthread.start() so ESP-IDF cannot create its fallback dataset.
    dataset = openthread.dataset_get()

    if dataset is None:
        return None

    dataset = normalize_dataset_hex(dataset)

    if (
        PROVISION_IGNORE_ESP_IDF_FALLBACK
        and dataset == ESP_IDF_FALLBACK_DATASET
    ):
        print("thread dataset: ESP-IDF fallback ignored")
        return None

    return dataset


def url_decode_form(value):
    value = value.replace("+", " ")
    out = bytearray()
    i = 0

    while i < len(value):
        ch = value[i]

        if ch == "%" and i + 2 < len(value):
            try:
                out.append(int(value[i + 1:i + 3], 16))
                i += 3
                continue
            except Exception:
                pass

        out.extend(ch.encode())
        i += 1

    return out.decode()


def parse_form(body):
    result = {}

    try:
        text = body.decode()
    except Exception:
        return result

    for item in text.split("&"):
        if not item:
            continue

        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key, value = item, ""

        result[url_decode_form(key)] = url_decode_form(value)

    return result


def html_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def provisioning_page(host, message="", error=False):
    notice = ""

    if message:
        css_class = "error" if error else "ok"
        notice = '<p class="{}">{}</p>'.format(
            css_class,
            html_escape(message),
        )

    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ESP32-C6 Thread setup</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 32px auto; padding: 0 16px; background: #111; color: #eee; }
    .card { background: #1b1b1b; border: 1px solid #333; border-radius: 16px; padding: 20px; }
    textarea { box-sizing: border-box; width: 100%; min-height: 180px; padding: 12px; border: 1px solid #555; border-radius: 10px; background: #0d0d0d; color: #eee; font-family: monospace; overflow-wrap: anywhere; }
    button { margin-top: 12px; padding: 11px 18px; border: 0; border-radius: 10px; font-size: 16px; }
    code { color: #9cdcfe; }
    .muted { color: #aaa; }
    .ok { color: #8bdc8b; }
    .error { color: #ff8f8f; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Thread Active Dataset</h2>
    <p>Device: <code>%%HOST%%</code></p>
    %%NOTICE%%
    <form method="post" action="/dataset">
      <label for="dataset">Paste the hexadecimal Active Dataset TLVs:</label>
      <textarea id="dataset" name="dataset" spellcheck="false" autocomplete="off" required></textarea>
      <button type="submit">Save and reboot</button>
    </form>
    <p class="muted">The dataset is written directly to OpenThread NVS. It is not printed to the serial log.</p>
  </div>
</body>
</html>
""".replace("%%HOST%%", html_escape(host)).replace("%%NOTICE%%", notice)


def http_response(body, status="200 OK", content_type="text/html; charset=utf-8"):
    if isinstance(body, str):
        body = body.encode()

    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: {}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "Content-Length: {}\r\n"
        "\r\n"
    ).format(status, content_type, len(body))

    return header.encode() + body


def send_all(sock, data):
    offset = 0

    while offset < len(data):
        sent = sock.send(data[offset:])
        if not sent:
            raise OSError("socket closed while sending")
        offset += sent


def recv_http_request(client):
    data = bytearray()
    header_end = -1

    while len(data) < PROVISION_MAX_REQUEST:
        chunk = client.recv(512)
        if not chunk:
            break

        data.extend(chunk)
        header_end = data.find(b"\r\n\r\n")
        if header_end >= 0:
            break

    if header_end < 0:
        raise ValueError("incomplete HTTP request")

    header_bytes = bytes(data[:header_end])
    body = bytes(data[header_end + 4:])
    lines = header_bytes.split(b"\r\n")
    request_line = lines[0].split()

    if len(request_line) < 2:
        raise ValueError("invalid HTTP request line")

    method = request_line[0].decode().upper()
    path = request_line[1].decode().split("?", 1)[0]
    content_length = 0

    for line in lines[1:]:
        if b":" not in line:
            continue

        name, value = line.split(b":", 1)
        if name.strip().lower() == b"content-length":
            content_length = int(value.strip())
            break

    if content_length < 0 or content_length > PROVISION_MAX_REQUEST:
        raise ValueError("invalid Content-Length")

    while len(body) < content_length:
        remaining = content_length - len(body)
        chunk = client.recv(min(512, remaining))
        if not chunk:
            break
        body += chunk

    if len(body) != content_length:
        raise ValueError("incomplete HTTP body")

    return method, path, body


def get_wpa2_security(network):
    try:
        return network.WLAN.SEC_WPA2
    except AttributeError:
        return network.AUTH_WPA2_PSK


def configure_provision_ap(network, ap, ssid, password):
    if len(password) < 8:
        raise ValueError("provision AP password must be at least 8 characters")

    ap.active(False)
    security = get_wpa2_security(network)
    configured = False

    # Newer MicroPython WLAN API.
    try:
        ap.config(
            ssid=ssid,
            key=password,
            security=security,
            channel=PROVISION_AP_CHANNEL,
        )
        configured = True
    except Exception:
        pass

    # Compatibility with older ESP32 MicroPython WLAN names.
    if not configured:
        ap.config(
            essid=ssid,
            password=password,
            authmode=security,
            channel=PROVISION_AP_CHANNEL,
        )

    ap.active(True)
    ap.ifconfig((
        PROVISION_AP_ADDR,
        "255.255.255.0",
        PROVISION_AP_ADDR,
        PROVISION_AP_ADDR,
    ))


def start_dataset_provisioning(openthread, host):
    import network
    import socket

    ap_id = get_wlan_interface_id(network, "AP")
    sta_id = get_wlan_interface_id(network, "STA")

    try:
        network.WLAN(sta_id).active(False)
    except Exception:
        pass

    ap = network.WLAN(ap_id)
    ssid = dns_label(host + "-thread-setup")[:32]
    configure_provision_ap(network, ap, ssid, PROVISION_AP_PASSWORD)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PROVISION_HTTP_PORT))
    server.listen(2)

    print("thread dataset: not configured")
    print("provision AP SSID:", ssid)
    print("provision AP password:", PROVISION_AP_PASSWORD)
    print("provision URL: http://{}/".format(PROVISION_AP_ADDR))

    while True:
        client = None

        try:
            client, _addr = server.accept()
            client.settimeout(5)
            method, path, body = recv_http_request(client)

            if method == "POST" and path == "/dataset":
                form = parse_form(body)

                try:
                    dataset = normalize_dataset_hex(form.get("dataset", ""))
                    openthread.dataset_set(dataset)

                    if thread_dataset_get(openthread) is None:
                        raise OSError("dataset was not stored")

                except Exception as exc:
                    response = provisioning_page(
                        host,
                        "Dataset rejected: {}".format(exc),
                        error=True,
                    )
                    send_all(client, http_response(response, "400 Bad Request"))
                    continue

                response = provisioning_page(
                    host,
                    "Dataset saved. Device is rebooting.",
                )

                try:
                    send_all(client, http_response(response))
                except Exception as exc:
                    print("provision response error:", exc)

                try:
                    client.close()
                except Exception:
                    pass

                time.sleep_ms(750)

                try:
                    ap.active(False)
                except Exception:
                    pass

                machine.reset()

            elif method == "GET":
                send_all(client, http_response(provisioning_page(host)))

            else:
                send_all(
                    client,
                    http_response(
                        "Method not allowed\n",
                        "405 Method Not Allowed",
                        "text/plain; charset=utf-8",
                    ),
                )

        except Exception as exc:
            print("provision HTTP error:", exc)

            try:
                if client:
                    send_all(
                        client,
                        http_response(
                            "Bad request\n",
                            "400 Bad Request",
                            "text/plain; charset=utf-8",
                        ),
                    )
            except Exception:
                pass

        finally:
            try:
                if client:
                    client.close()
            except Exception:
                pass

_srp_watchdog_started = False
_srp_watchdog_last_success_ms = None
_srp_watchdog_unregistered_since_ms = None
_srp_watchdog_last_event = None
_srp_watchdog_last_error = None
_srp_watchdog_last_restart_ms = None
_srp_watchdog_restarts = 0


def srp_is_registered(status):
    if not status.get("running"):
        return False

    host = status.get("srp_host") or {}
    if host.get("state") != "Registered":
        return False

    services = status.get("services") or []
    if not services:
        return False

    for service in services:
        if service.get("state") != "Registered":
            return False

    return True


def restart_srp_client(openthread, reason):
    global _srp_watchdog_last_restart_ms
    global _srp_watchdog_restarts

    print("srp watchdog: restarting client:", reason)

    try:
        openthread.srp_client_stop()
    except Exception as exc:
        print("srp watchdog: stop failed:", exc)

    time.sleep_ms(SRP_WATCHDOG_RESTART_DELAY_MS)

    try:
        # otSrpClientStop() disables auto-start. Re-enabling it keeps the
        # existing host and services and marks them for a fresh SRP Update.
        openthread.srp_client_autostart(True)
        _srp_watchdog_last_restart_ms = time.ticks_ms()
        _srp_watchdog_restarts += 1
        print("srp watchdog: auto-start enabled")
        return True
    except Exception as exc:
        print("srp watchdog: restart failed:", exc)
        return False


def srp_watchdog_status():
    now = time.ticks_ms()
    age_ms = None

    if _srp_watchdog_last_success_ms is not None:
        age_ms = time.ticks_diff(now, _srp_watchdog_last_success_ms)

    return {
        "started": _srp_watchdog_started,
        "lease": SRP_LEASE,
        "key_lease": SRP_KEY_LEASE,
        "ttl": SRP_TTL,
        "last_success_age_ms": age_ms,
        "last_event": _srp_watchdog_last_event,
        "last_error": _srp_watchdog_last_error,
        "last_restart_ms": _srp_watchdog_last_restart_ms,
        "restarts": _srp_watchdog_restarts,
    }


def srp_watchdog_worker():
    global _srp_watchdog_started
    global _srp_watchdog_last_success_ms
    global _srp_watchdog_unregistered_since_ms
    global _srp_watchdog_last_event
    global _srp_watchdog_last_error

    import openthread

    now = time.ticks_ms()
    _srp_watchdog_last_success_ms = now
    _srp_watchdog_unregistered_since_ms = None

    # Drain boot-time events. The watchdog keeps a summary in
    # srp_watchdog_status() so the small C-side queue does not overflow.
    try:
        openthread.srp_client_events()
    except Exception:
        pass

    try:
        while True:
            now = time.ticks_ms()
            thread_heartbeat("srp-watchdog")

            try:
                state = openthread.state()
                attached = state in ("child", "router", "leader")

                for event in openthread.srp_client_events():
                    _srp_watchdog_last_event = event

                    if (
                        event.get("type") == "update"
                        and event.get("error_name") == "None"
                        and event.get("host_state") == "Registered"
                    ):
                        _srp_watchdog_last_success_ms = now
                        _srp_watchdog_last_error = None
                    elif event.get("error_name") not in (None, "None"):
                        _srp_watchdog_last_error = event.get("error_name")

                status = openthread.srp_client()
                registered = srp_is_registered(status)

                if not attached:
                    # Give auto-start a fresh watchdog interval after a detach.
                    _srp_watchdog_last_success_ms = now
                    _srp_watchdog_unregistered_since_ms = None

                elif registered:
                    _srp_watchdog_unregistered_since_ms = None
                    stale_ms = time.ticks_diff(
                        now,
                        _srp_watchdog_last_success_ms,
                    )

                    if stale_ms >= SRP_WATCHDOG_STALE_MS:
                        reason = "no successful update for {} ms".format(
                            stale_ms
                        )

                        if restart_srp_client(openthread, reason):
                            _srp_watchdog_last_success_ms = now

                else:
                    if _srp_watchdog_unregistered_since_ms is None:
                        _srp_watchdog_unregistered_since_ms = now

                    unregistered_ms = time.ticks_diff(
                        now,
                        _srp_watchdog_unregistered_since_ms,
                    )

                    if unregistered_ms >= SRP_WATCHDOG_UNREGISTERED_MS:
                        reason = "not registered for {} ms".format(
                            unregistered_ms
                        )

                        if restart_srp_client(openthread, reason):
                            _srp_watchdog_last_success_ms = now
                            _srp_watchdog_unregistered_since_ms = None

            except Exception as exc:
                _srp_watchdog_last_error = str(exc)
                print("srp watchdog error:", exc)

            time.sleep_ms(SRP_WATCHDOG_POLL_MS)

    finally:
        _srp_watchdog_started = False


def start_srp_watchdog():
    global _srp_watchdog_started

    if not SRP_WATCHDOG_ENABLED:
        print("srp watchdog: disabled")
        return False

    if _srp_watchdog_started:
        print("srp watchdog: already started")
        return False

    _srp_watchdog_started = True

    try:
        thread_id = start_tracked_thread(
            "srp-watchdog",
            srp_watchdog_worker,
        )
        print("srp watchdog: started", thread_id)
        return True
    except Exception as exc:
        _srp_watchdog_started = False
        print("srp watchdog start failed:", exc)
        return False


def boot_thread_webrepl():
    import openthread

    host = get_host_name()

    print("uid:", machine.unique_id().hex().lower())
    print("model:", get_mcu_model())
    print("host:", host)

    openthread.init()

    # erase_persistent() requires an initialized OpenThread instance. Perform
    # the optional contact reset before reading or starting the saved dataset.
    if check_factory_reset(openthread):
        return

    # This check must happen after init() and before start(). Starting Thread
    # without a dataset can cause ESP-IDF to generate its development fallback.
    if thread_dataset_get(openthread) is None:
        start_dataset_provisioning(openthread, host)
        return

    print("thread dataset: configured")
    openthread.start(routereligible=True, sleepy=False)

    try:
        openthread.set_default_netif()
        print("thread default netif: ok")
    except Exception as exc:
        print("thread default netif skipped:", exc)

    # Configure the SRP host and services before waiting for Thread attach.
    # OpenThread auto-start keeps monitoring Thread Network Data and starts the
    # SRP client when an SRP server becomes available, including after a late
    # network attachment.
    try:
        register_srp_webrepl(openthread, host)
        print("srp auto-start: configured")
    except Exception as exc:
        print("srp setup failed:", exc)

    attached = wait_thread_attached(openthread, 60)

    if not attached:
        print("thread attach pending; SRP auto-start remains enabled")

        try:
            configure_dns_from_thread_netdata(openthread)
        except Exception as exc:
            print("thread dns configure failed:", exc)

    start_webrepl6(WEBREPL_PASSWORD, WEBREPL_PORT, host)

    if APP_AUTOSTART:
        start_app_thread(APP_FILE)

    start_srp_watchdog()

    print("boot.py done")


def is_valid_ipv6_addr(addr):
    if not addr:
        return False

    if addr in ("::", "0.0.0.0"):
        return False

    # Thread DNS must use an IPv6 address.
    if ":" not in addr:
        return False

    return True


def dump_thread_netdata(openthread):
    try:
        print("thread netdata:", openthread.netdata())
    except Exception as exc:
        print("thread netdata read failed:", exc)

    try:
        services = openthread.netdata_services()
        print("thread netdata services:", services)
        return services
    except Exception as exc:
        print("thread netdata services read failed:", exc)
        return []


def wait_srp_server_addr(openthread, timeout_s=30):
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        try:
            srp = openthread.srp_client()
            print("srp client:", srp)

            addr = srp.get("server_addr", "")
            if is_valid_ipv6_addr(addr):
                return addr

        except Exception as exc:
            print("srp client read failed:", exc)

        time.sleep(1)

    return None


def configure_dns_from_thread_netdata(openthread):
    services = dump_thread_netdata(openthread)

    dns_srp_found = False

    for service in services:
        # Thread enterprise number.
        if service.get("enterprise_number") == 44970:
            dns_srp_found = True
            print("thread dns/srp service:", service)

    if not dns_srp_found:
        print("warning: no Thread DNS/SRP service found in Network Data")
        return False

    # SRP autostart uses Thread Network Data discovery inside OpenThread.
    try:
        openthread.srp_client_autostart(True)
    except Exception as exc:
        print("srp autostart enable failed:", exc)

    dns_addr = wait_srp_server_addr(openthread, 30)

    if not dns_addr:
        print("warning: no SRP/DNS server address discovered")
        return False

    try:
        print("setting lwIP DNS[0]:", dns_addr)
        print(openthread.dns_set(dns_addr, 0))
        return True
    except Exception as exc:
        print("dns_set failed:", exc)
        return False


_boot_worker_started = False


def boot_worker():
    global _boot_worker_started

    try:
        boot_thread_webrepl()
    except Exception as exc:
        print("boot.py worker failed:", exc)
    finally:
        _boot_worker_started = False


def start_boot_worker():
    global _boot_worker_started

    if _boot_worker_started:
        print("boot.py worker: already started")
        return False

    _boot_worker_started = True

    try:
        thread_id = start_tracked_thread(
            "boot-worker",
            boot_worker,
        )
    except Exception as exc:
        _boot_worker_started = False
        print("boot.py worker start failed:", exc)
        return False

    print(
        "boot.py worker: started; serial REPL remains available",
        thread_id,
    )
    return True


start_boot_worker()
