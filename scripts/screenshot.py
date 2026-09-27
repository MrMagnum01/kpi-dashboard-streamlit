#!/usr/bin/env python3
"""QA script: launch the dashboard locally and screenshot it at phone (390px)
and desktop widths, using headless google-chrome driven over raw CDP
(Chrome DevTools Protocol) - no Selenium/Playwright. Both the `streamlit
run` process and the `google-chrome` process are started here and killed
here, by PID, when the script exits (including on error).

Requires `google-chrome` on PATH and the `websocket-client` package
(dev-only tooling; not a runtime dependency of the dashboard itself, so
it is not in requirements.txt - install it ad hoc to run this script:
`pip install websocket-client`).

Usage:
    PYTHONPATH=src python3 scripts/screenshot.py [output_dir]
"""

from __future__ import annotations

import base64
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

REPO_ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_http(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception as exc:  # noqa: BLE001 - polling loop, retried until deadline
            last_exc = exc
            time.sleep(0.5)
    raise TimeoutError(f"{url} did not respond in time: {last_exc}")


def cdp_screenshot(chrome_port: int, target_url: str, width: int, height: int, out_path: Path) -> None:
    req = urllib.request.Request(f"http://127.0.0.1:{chrome_port}/json/new?about:blank", method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        info = json.loads(r.read())
    ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=30)
    msg_id = 0

    def send(method, params=None):
        nonlocal msg_id
        msg_id += 1
        this_id = msg_id
        ws.send(json.dumps({"id": this_id, "method": method, "params": params or {}}))
        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == this_id:
                return resp

    try:
        send("Page.enable")
        send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 500},
        )
        send("Page.navigate", {"url": target_url})
        time.sleep(6)  # let Streamlit's client-side render settle; raw CDP has no auto-wait
        result = send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
            },
        )
        out_path.write_bytes(base64.b64decode(result["result"]["data"]))
    finally:
        ws.close()


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    streamlit_port = free_port()
    chrome_port = free_port()

    env = dict(os.environ)
    env["KPI_DASHBOARD_DB"] = str(REPO_ROOT / "data" / "sample" / "reconciliation.duckdb")

    streamlit_proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(REPO_ROOT / "streamlit_app.py"),
            "--server.address", "127.0.0.1",
            "--server.port", str(streamlit_port),
            "--server.headless", "true",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    chrome_profile = out_dir / ".chrome-profile"
    chrome_proc = subprocess.Popen(
        [
            "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={chrome_port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={chrome_profile}",
            "--window-size=1440,900",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        wait_for_http(f"http://127.0.0.1:{streamlit_port}/", timeout=30)
        wait_for_http(f"http://127.0.0.1:{chrome_port}/json/version", timeout=15)

        url = f"http://127.0.0.1:{streamlit_port}/"
        cdp_screenshot(chrome_port, url, 390, 844, out_dir / "dashboard-390.png")
        cdp_screenshot(chrome_port, url, 1440, 900, out_dir / "dashboard-desktop.png")
        print(f"Wrote {out_dir / 'dashboard-390.png'} and {out_dir / 'dashboard-desktop.png'}")
    finally:
        # Kill both processes by PID, never by port/name-matching.
        for proc, name in ((chrome_proc, "chrome"), (streamlit_proc, "streamlit")):
            try:
                os.kill(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    pass


if __name__ == "__main__":
    main()
