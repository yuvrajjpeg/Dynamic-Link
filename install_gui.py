#!/usr/bin/env python3
"""Open the Dynamic Bridge installer window: a local page that runs install.install()."""
import contextlib
import io
import json
import platform
import plistlib
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import install

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "installer" / "index.html"
ICON = ROOT / "installer" / "icon.svg"
# index.html is written as a bare fragment (it is also published as a preview), so supply the document head here.
HEAD = (b'<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
        b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
RESOLVE_APPS = (Path("/Applications/DaVinci Resolve/DaVinci Resolve.app"), Path("/Applications/DaVinci Resolve.app"))
TOKEN = secrets.token_urlsafe(16)


def app_version(app):
    try:
        with open(app / "Contents/Info.plist", "rb") as handle:
            return plistlib.load(handle).get("CFBundleShortVersionString") or "unknown"
    except (OSError, plistlib.InvalidFileException):
        return "unknown"


def resolve_edition_problem(app):
    """Name the Resolve builds the bridge cannot drive, or None when the edition looks usable."""
    if (app / "Contents/_MASReceipt").exists():
        return ("Mac App Store edition: sandboxed, so it cannot see the bridge's scripts or control After Effects. "
                "Install DaVinci Resolve Studio from blackmagicdesign.com.")
    try:
        with open(app / "Contents/Info.plist", "rb") as handle:
            bundle = plistlib.load(handle).get("CFBundleIdentifier", "")
    except (OSError, plistlib.InvalidFileException):
        bundle = ""
    if bundle.endswith("Lite"):
        return "Free edition: no external scripting, so renders cannot return to the timeline. Studio is required."
    return None


def tilde(path, home):
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def configured_after_effects(config):
    try:
        return Path(json.loads(config.read_text())["after_effects_app"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def preflight(home):
    target, scripts = install.destinations(home)
    config = target / "config.json"
    on_mac = sys.platform == "darwin"
    new_python = sys.version_info >= (3, 9)
    resolve = next((app for app in RESOLVE_APPS if app.exists()), None)
    edition_problem = resolve and resolve_edition_problem(resolve)
    ae = configured_after_effects(config) if config.exists() else None
    ae = ae if ae and ae.exists() else install.find_after_effects()
    ae = ae if ae and ae.exists() else None
    checks = [
        {"label": "macOS", "state": "ok" if on_mac else "fail",
         "detail": f"macOS {platform.mac_ver()[0]}" if on_mac else "This prototype supports macOS only."},
        {"label": "Python 3.9 or later", "state": "ok" if new_python else "fail",
         "detail": f"Python {platform.python_version()} · {sys.executable}"},
        {"label": "DaVinci Resolve (Studio required)", "state": "warn",
         "detail": f"Version {app_version(resolve)}. {edition_problem}" if edition_problem
         else f"Version {app_version(resolve)} found. Studio edition must be confirmed in Resolve." if resolve
         else "Not found in /Applications. Studio 21.1 or later is required."},
        {"label": "After Effects", "state": "ok" if ae else "warn",
         "detail": f"Version {app_version(ae)} · {ae}" if ae
         else "Not found. Choose its app below, or install AE and rerun this installer."},
    ]
    return {
        "checks": checks,
        "can_install": on_mac and new_python,
        "config_exists": config.exists(),
        "scripts": sorted(path.stem for path in (ROOT / "scripts").glob("*.py")),
        "paths": {"scripts": tilde(scripts, home), "plugin": tilde(target / "plugin", home),
                  "config": tilde(config, home)},
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.send(200, HEAD + PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/icon.svg":
            self.send(200, ICON.read_bytes(), "image/svg+xml")
        elif path == "/api/preflight":
            if self.authorized():
                self.reply(200, preflight(Path.home()))
        else:
            self.send(404, b"Not found", "text/plain")

    def do_POST(self):
        if not self.authorized():
            return
        if self.path == "/api/install":
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 8192:
                    raise ValueError("Installer request is too large.")
                body = json.loads(self.rfile.read(size) or b"{}")
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    report = install.install(Path.home(), body.get("ae_app") or None)
            except Exception as error:  # any copy or permission failure is shown in the window
                return self.reply(500, {"error": f"{type(error).__name__}: {error}"})
            self.reply(200, {"log": output.getvalue().splitlines(), "report": report})
        elif self.path == "/api/reveal":
            target, _ = install.destinations(Path.home())
            subprocess.run(["open", "-R", str(target / "config.json")], check=False)
            self.reply(200, {})
        elif self.path == "/api/quit":
            self.reply(200, {})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.reply(404, {"error": "Unknown installer action."})

    def authorized(self):
        if secrets.compare_digest(self.headers.get("X-Installer-Token", ""), TOKEN):
            return True
        self.reply(403, {"error": "This installer window has expired. Open Install.command again."})
        return False

    def reply(self, status, data):
        self.send(status, json.dumps(data).encode(), "application/json")

    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/?t={TOKEN}"
    print("The Dynamic Bridge installer is open in your browser.")
    print("If it did not open, visit", url)
    print("Press Ctrl+C to quit.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
