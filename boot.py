# /flash/boot.py

import time
import os
import machine


WEBREPL_PASSWORD = "1234"
WEBREPL_PORT = 8266

SRP_SERVICE_INSTANCE = "esp32-webrepl"
SRP_SERVICE_TYPE = "_webrepl._tcp"

# Requested SRP client lease settings.
# The OTBR SRP Server can still clamp these values to its min/max policy.
SRP_LEASE = 600
SRP_KEY_LEASE = 1800
SRP_TTL = 600

APP_AUTOSTART = True
# Use app.py or main.py for user code, not simultaneously.
APP_FILE = "app.py"

# NOTE:
# After openthread.erase_persistent() the saved Thread dataset is removed,
# but ESP-IDF/OpenThread may expose a default fallback dataset
# such as "OpenThread" / dead00beef / fddead....
# This boot.py intentionally auto-starts OpenThread if a dataset is present.
# For a real factory reset, disable this boot script or flash/set a real dataset
# before calling openthread.start().


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
    return "{}-{}".format(get_mcu_model(), uid[-12:])


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
        SRP_SERVICE_INSTANCE,
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
        import _thread
    except Exception as exc:
        print("warning: _thread unavailable:", exc)
        return False

    try:
        _thread.start_new_thread(run_app_file, (path,))
        print("app thread: started", path)
        return True
    except Exception as exc:
        print("warning: app thread failed:", exc)
        return False


def boot_thread_webrepl():
    import openthread

    host = get_host_name()

    print("uid:", machine.unique_id().hex().lower())
    print("model:", get_mcu_model())
    print("host:", host)

    openthread.init()
    openthread.start(routereligible=True, sleepy=False)

    try:
        openthread.set_default_netif()
        print("thread default netif: ok")
    except Exception as exc:
        print("thread default netif skipped:", exc)

    attached = wait_thread_attached(openthread, 60)

    if attached:
        try:
            register_srp_webrepl(openthread, host)
        except Exception as exc:
            print("srp register failed:", exc)

        try:
            configure_dns_from_thread_netdata(openthread)
        except Exception as exc:
            print("thread dns configure failed:", exc)

    start_webrepl6(WEBREPL_PASSWORD, WEBREPL_PORT, host)

    if APP_AUTOSTART:
        start_app_thread(APP_FILE)

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


try:
    boot_thread_webrepl()
except Exception as exc:
    print("boot.py failed:", exc)
