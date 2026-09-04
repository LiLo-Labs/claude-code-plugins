"""Socket client for the BlendPipe addon running inside Blender.

Deliberately dependency-free and synchronous. Blender executes one job at a time
on its main thread anyway, so concurrency here would buy nothing and would make
the failure modes much harder to explain.
"""

import json
import os
import socket

DEFAULT_HOST = os.environ.get("BLENDPIPE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("BLENDPIPE_PORT", "9876"))


class BridgeError(RuntimeError):
    """Raised when Blender is unreachable or reports a failure."""


NOT_RUNNING = (
    "Cannot reach Blender on {host}:{port}.\n"
    "Blender must be open with the BlendPipe addon enabled and started:\n"
    "  1. Edit > Preferences > Add-ons > Install, choose blendpipe/addon.py\n"
    "  2. Enable 'Interface: BlendPipe Bridge'\n"
    "  3. In the 3D viewport press N, open the BlendPipe tab, press Start\n"
    "Set BLENDPIPE_PORT if you changed the port in that panel."
)


def call(command, params=None, timeout=600.0, host=None, port=None):
    """Send one command and return its `data` payload.

    Raises BridgeError for both transport failures and errors reported by the
    addon, because from the caller's point of view they need the same response:
    say what went wrong and do not pretend the scene changed.
    """
    host = host or DEFAULT_HOST
    port = port or DEFAULT_PORT
    request = json.dumps(
        {"command": command, "params": params or {}, "timeout": timeout}
    ).encode("utf-8") + b"\n"

    try:
        with socket.create_connection((host, port), timeout=10.0) as sock:
            # The connect timeout is short so an absent Blender fails fast, but
            # the read timeout has to cover the work itself — a Cycles render or
            # a heavy remesh legitimately takes minutes.
            sock.settimeout(timeout + 15.0)
            sock.sendall(request)
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    raise BridgeError("Blender closed the connection mid-reply")
                buf += chunk
    except (ConnectionRefusedError, socket.gaierror, OSError) as exc:
        if isinstance(exc, socket.timeout):
            raise BridgeError("Blender did not reply within %.0fs" % timeout) from exc
        raise BridgeError(NOT_RUNNING.format(host=host, port=port)) from exc

    try:
        response = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except Exception as exc:
        raise BridgeError("unreadable reply from Blender: %s" % exc) from exc

    if not response.get("ok"):
        detail = response.get("error", "unknown error")
        trace = response.get("traceback")
        raise BridgeError(detail + ("\n" + trace if trace else ""))
    return response.get("data")


def is_running(host=None, port=None):
    try:
        call("ping", timeout=5.0, host=host, port=port)
        return True
    except BridgeError:
        return False
