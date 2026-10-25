#!/usr/bin/env python3
"""Install only this bridge's files in the current macOS user's directories."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent


def destinations(home):
    """Return the bridge's support folder and Resolve's Utility scripts folder."""
    return (home / "Library/Application Support/Resolve AE Bridge",
            home / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility")


def find_after_effects():
    apps = sorted(app for root in (Path("/Applications"), Path.home() / "Applications")
                  for app in root.glob("Adobe After Effects*/Adobe After Effects*.app"))
    return apps[-1] if apps else None


def install(home, ae_app=None):
    target, scripts = destinations(home)
    config = target / "config.json"
    cfg = json.loads(config.read_text()) if config.exists() else {}
    configured = Path(cfg.get("after_effects_app", "/missing"))
    app = Path(ae_app).expanduser() if ae_app else (configured if configured.is_dir() else find_after_effects())
    if home != Path.home() and ae_app is None:
        app = None  # A staging install must not write to a real host application.
    if app and (not app.is_dir() or app.suffix != ".app" or not (app / "Contents/Info.plist").is_file()):
        raise ValueError("Choose the installed Adobe After Effects .app bundle.")
    (target / "plugin").mkdir(parents=True, exist_ok=True)
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("bridge.py", "create_composition.jsx", "Resolve AE Bridge.jsx"):
        shutil.copy2(ROOT / "resolve_ae" / name, target / "plugin" / name)
    for source in (ROOT / "scripts").glob("*.py"):
        shutil.copy2(source, scripts / source.name)
    if app:
        cfg["after_effects_app"] = str(app)
        if ae_app or not Path(cfg.get("aerender", "/missing")).is_file():
            cfg["aerender"] = str(app.parent / "aerender")
    cfg["python"] = sys.executable
    cfg.setdefault("output_module", "Resolve Bridge ProRes")
    cfg.setdefault("jobs_directory", str(home / "Movies/Resolve AE Bridge"))
    config.write_text(json.dumps(cfg, indent=2) + "\n")
    report = {"resolve": "installed", "after_effects": "pending", "warnings": []}
    if app:
        ae_scripts = app.parent / "Scripts"
        try:
            ae_scripts.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "resolve_ae/Resolve AE Bridge.jsx", ae_scripts / "Resolve AE Bridge.jsx")
            report["after_effects"] = "installed"
            report["ae_script"] = str(ae_scripts / "Resolve AE Bridge.jsx")
            if not Path(cfg["aerender"]).is_file():
                report["warnings"].append("AE companion installed, but aerender is missing. Repair the AE installation before sending footage.")
        except PermissionError:
            report["warnings"].append("After Effects' Scripts folder is not writable: " + str(ae_scripts) +
                                      ". Grant your user write access to that folder and run this installer again.")
    else:
        report["warnings"].append("After Effects was not found. Install it, then rerun this installer to finish both-app setup.")
    (target / "installation.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Installed scripts in", scripts)
    print("Configuration:", config)
    print("After Effects companion:", report["after_effects"])
    for warning in report["warnings"]:
        print(warning)
    print("Restart both apps. The first handoff configures a compatible QuickTime template when available.")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, default=Path.home(), help="Override destination home for staging/tests")
    parser.add_argument("--ae-app", type=Path, help="After Effects .app location, if not detected")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This prototype supports macOS only.")
    if sys.version_info < (3, 9):
        parser.error("Python 3.9+ is required.")
    install(args.home, args.ae_app)
