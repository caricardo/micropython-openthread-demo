# /flash/app.py

import time
import socket
import machine
import neopixel


RGB_PIN = 8
RGB_COUNT = 1
HTTP_PORT = 80

SERVICE_INSTANCE_PREFIX = "esp32-rgb"
SERVICE_TYPE = "_http._tcp"

# Limit brightness to avoid blinding full-power RGB.
MAX_BRIGHTNESS = 96


np = neopixel.NeoPixel(machine.Pin(RGB_PIN), RGB_COUNT)
current_color = (0, 0, 0)


def clamp(value, lo=0, hi=255):
    try:
        value = int(value)
    except Exception:
        value = 0

    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def scale_color(r, g, b):
    r = clamp(r)
    g = clamp(g)
    b = clamp(b)

    m = max(r, g, b)
    if m <= MAX_BRIGHTNESS:
        return r, g, b

    return (
        int(r * MAX_BRIGHTNESS / m),
        int(g * MAX_BRIGHTNESS / m),
        int(b * MAX_BRIGHTNESS / m),
    )


def set_rgb(r, g, b):
    global current_color

    color = scale_color(r, g, b)
    current_color = color

    for i in range(RGB_COUNT):
        np[i] = color

    np.write()
    return color


def set_hex(hex_color):
    if not hex_color:
        return current_color

    if hex_color.startswith("#"):
        hex_color = hex_color[1:]

    if len(hex_color) != 6:
        return current_color

    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except Exception:
        return current_color

    return set_rgb(r, g, b)


def color_to_hex(color):
    r, g, b = color
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def url_decode(text):
    text = text.replace("+", " ")
    out = ""
    i = 0

    while i < len(text):
        if text[i] == "%" and i + 2 < len(text):
            try:
                out += chr(int(text[i + 1:i + 3], 16))
                i += 3
                continue
            except Exception:
                pass

        out += text[i]
        i += 1

    return out


def parse_query(path):
    query = {}

    if "?" not in path:
        return path, query

    path, qs = path.split("?", 1)

    for item in qs.split("&"):
        if not item:
            continue

        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key, value = item, ""

        query[url_decode(key)] = url_decode(value)

    return path, query


def parse_request_path(request):
    try:
        first_line = request.split(b"\r\n", 1)[0]
        parts = first_line.split()
        if len(parts) >= 2:
            return parts[1].decode()
    except Exception:
        pass

    return "/"


def html_page():
    color_hex = color_to_hex(current_color)

    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ESP32-C6 RGB</title>
  <style>
    body {
      font-family: system-ui, sans-serif;
      max-width: 520px;
      margin: 32px auto;
      padding: 0 16px;
      background: #111;
      color: #eee;
    }
    .card {
      border: 1px solid #333;
      border-radius: 16px;
      padding: 20px;
      background: #1b1b1b;
    }
    input[type=color] {
      width: 100%;
      height: 90px;
      border: 0;
      background: transparent;
    }
    button {
      display: inline-block;
      margin: 6px 4px 0 0;
      padding: 10px 14px;
      border: 0;
      border-radius: 10px;
      background: #333;
      color: #fff;
      font-size: 15px;
    }
    .status {
      margin-top: 14px;
      color: #aaa;
      font-family: monospace;
    }
  </style>
</head>
<body>
  <div class="card">
    <h2>ESP32-C6 RGB</h2>

    <input id="picker" type="color" value="%%COLOR%%">

    <p>
      <button onclick="setColor()">Set color</button>
      <button onclick="quick('#ff0000')">Red</button>
      <button onclick="quick('#00ff00')">Green</button>
      <button onclick="quick('#0000ff')">Blue</button>
      <button onclick="quick('#ffffff')">White</button>
      <button onclick="quick('#000000')">Off</button>
    </p>

    <div class="status">
      current: <span id="current">%%COLOR%%</span>
    </div>
  </div>

  <script>
    function setColor() {
      var color = document.getElementById("picker").value;
      fetch("/set?hex=" + encodeURIComponent(color.substring(1)))
        .then(function(r) { return r.text(); })
        .then(function(t) {
          document.getElementById("current").textContent = color;
        });
    }

    function quick(color) {
      document.getElementById("picker").value = color;
      setColor();
    }
  </script>
</body>
</html>
"""

    return html.replace("%%COLOR%%", color_hex)


def http_response(body, content_type="text/html; charset=utf-8", status="200 OK"):
    if isinstance(body, str):
        body = body.encode()

    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: {}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-cache\r\n"
        "Content-Length: {}\r\n"
        "\r\n"
    ).format(status, content_type, len(body))

    return header.encode() + body


def handle_request(path):
    path, query = parse_query(path)

    if path == "/set":
        color = set_hex(query.get("hex", ""))
        return http_response(
            "OK {}\n".format(color_to_hex(color)),
            "text/plain; charset=utf-8",
        )

    if path == "/off":
        color = set_rgb(0, 0, 0)
        return http_response(
            "OK {}\n".format(color_to_hex(color)),
            "text/plain; charset=utf-8",
        )

    if path == "/status":
        return http_response(
            "color={}\n".format(color_to_hex(current_color)),
            "text/plain; charset=utf-8",
        )

    if path == "/test":
        set_rgb(255, 0, 0)
        time.sleep_ms(200)
        set_rgb(0, 255, 0)
        time.sleep_ms(200)
        set_rgb(0, 0, 255)
        time.sleep_ms(200)
        set_rgb(255, 255, 255)
        time.sleep_ms(200)
        set_rgb(0, 0, 0)

        return http_response("OK test\n", "text/plain; charset=utf-8")

    return http_response(html_page())


def register_http_service():
    # Do not initialize or start OpenThread here.
    # boot.py already owns Thread startup and SRP host registration.
    try:
        import openthread

        uid = machine.unique_id().hex().lower()
        service_instance = "{}-{}".format(SERVICE_INSTANCE_PREFIX, uid)

        openthread.srp_client_add_service(
            service_instance,
            SERVICE_TYPE,
            HTTP_PORT,
            0,
            0,
            {
                "svc": "rgb",
                "path": "/",
            },
        )

        print("http srp service:", service_instance + "." + SERVICE_TYPE)

    except Exception as exc:
        print("warning: http srp service failed:", exc)


def start_http_server():
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("::", HTTP_PORT))
    s.listen(2)

    print("rgb http: http://[::]:{}/".format(HTTP_PORT))

    while True:
        client = None

        try:
            client, addr = s.accept()
            request = client.recv(1024)
            path = parse_request_path(request)
            response = handle_request(path)
            client.send(response)

        except Exception as exc:
            print("rgb http error:", exc)

            try:
                if client:
                    client.send(
                        http_response(
                            "ERROR\n",
                            "text/plain; charset=utf-8",
                            "500 Internal Server Error",
                        )
                    )
            except Exception:
                pass

        try:
            if client:
                client.close()
        except Exception:
            pass


set_rgb(0, 0, 0)
register_http_service()
start_http_server()
