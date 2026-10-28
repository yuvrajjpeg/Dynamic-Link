"""Resolve ↔ After Effects bridge. macOS, Resolve Studio 21.1+.

No dependencies beyond Python and the applications' scripting APIs.
"""
from pathlib import Path
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
HOME = Path.home() / "Library/Application Support/Resolve AE Bridge"
CONFIG = HOME / "config.json"
LOG = logging.getLogger("resolve-ae")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def values(items):
    return list(items.values()) if isinstance(items, dict) else list(items or [])


def number(value):
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        raise ValueError("Cannot read numeric value: " + str(value))
    return float(match.group())


def settings():
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    apps = sorted(Path("/Applications").glob("Adobe After Effects*/*.app"))
    if not cfg.get("after_effects_app") and apps:
        cfg["after_effects_app"] = str(apps[-1])
    app = Path(cfg.get("after_effects_app", "/missing/After Effects.app")).expanduser()
    render = Path(cfg.get("aerender", str(app.parent / "aerender"))).expanduser()
    if not app.is_dir() or not render.is_file():
        raise RuntimeError("After Effects/aerender not found. Set after_effects_app and aerender in " + str(CONFIG))
    cfg.update(after_effects_app=str(app), aerender=str(render))
    cfg.setdefault("output_module", "Resolve Bridge ProRes")
    cfg.setdefault("jobs_directory", str(Path.home() / "Movies/Resolve AE Bridge"))
    cfg.setdefault("python", shutil.which("python3") or sys.executable)
    if not Path(cfg["python"]).is_file():
        raise RuntimeError("Set python in config.json to an installed Python 3.9+ executable.")
    return cfg


def context(resolve):
    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    if not timeline:
        raise RuntimeError("Open a Resolve project and timeline first.")
    return manager, project, timeline


def describe(resolve):
    _, project, timeline = context(resolve)
    # Resolve 21.0.4+ selection API; fall back to playhead only with no selection.
    selected = values(timeline.GetSelectedClips())
    video = [x for x in selected if x.GetTrackTypeAndIndex()[0] == "video"]
    if len(video) > 1:
        raise RuntimeError("Select exactly one video clip.")
    item = video[0] if video else timeline.GetCurrentVideoItem()
    if not item:
        raise RuntimeError("Select a video clip or put the playhead over one.")
    media = item.GetMediaPoolItem()
    if not media:
        raise RuntimeError("Choose an ordinary video file, not a generator or compound clip.")
    props = media.GetClipProperty()
    source = Path(props.get("File Path", ""))
    if not source.is_file() or source.suffix.lower() not in {".mov", ".mp4", ".mxf", ".avi", ".m4v", ".mts", ".m2ts"}:
        raise RuntimeError("This version supports ordinary video files; compound/multicam/RAW/sequence media is unsupported.")
    timeline_settings = timeline.GetSettings()
    fps = number(timeline_settings["timelineFrameRate"])
    source_fps = number(props.get("FPS"))
    if abs(source_fps - fps) > 0.01:
        raise RuntimeError("Source and timeline frame rates must match in this version.")
    duration = number(item.GetDuration())
    source_start = number(item.GetSourceStartFrame())
    source_end = number(item.GetSourceEndFrame())
    # Resolve source end is inclusive. Reject speed changes before making a job.
    if abs((source_end - source_start + 1) - duration) > 0.05:
        raise RuntimeError("Retimed, reversed, or freeze-frame clips are unsupported. Use an ordinary 100% speed shot.")
    speed = item.GetProperty().get("Speed", 100)
    if abs(number(speed) - 100) > 0.001:
        raise RuntimeError("Reset clip speed to 100% before sending.")
    offset = number(item.GetLeftOffset())
    if duration <= 0 or offset < 0 or abs(duration - round(duration)) > 0.001:
        raise RuntimeError("Invalid or fractional clip range.")
    return dict(project_id=project.GetUniqueId(), timeline_id=timeline.GetUniqueId(),
                clip_id=item.GetUniqueId(), original_media_id=media.GetUniqueId(),
                name=item.GetName(), source=str(source), fps=fps,
                frames=int(round(duration)), offset=offset,
                start=number(item.GetStart()), end=number(item.GetEnd()),
                track=list(item.GetTrackTypeAndIndex()), accepted_media_ids=[media.GetUniqueId()])


def make_jsx(job):
    template = (ROOT / "create_composition.jsx").read_text(encoding="utf-8")
    companion = (ROOT / "Resolve AE Bridge.jsx").read_text(encoding="utf-8")
    return ("$._resolveBridgeHeadless = true;\ntry {\n" + companion + "\n" +
            template.replace("/*BRIDGE_JOB*/null", json.dumps(job, ensure_ascii=True)) +
            "\n} finally { $._resolveBridgeHeadless = false; }\n")


def launch_ae(cfg, jsx):
    # Pass paths as argv, never interpolate them into AppleScript or shell code.
    script = '''on run argv
set targetApp to item 1 of argv
set scriptFile to item 2 of argv
using terms from application "Adobe After Effects"
tell application targetApp
activate
DoScriptFile scriptFile
end tell
end using terms from
end run'''
    # Compile terminology against the actual installed application, including its version.
    app_literal = cfg["after_effects_app"].replace("\\", "\\\\").replace('"', '\\"')
    script = script.replace('application "Adobe After Effects"', 'application "' + app_literal + '"')
    result = subprocess.run(["/usr/bin/osascript", "-e", script, cfg["after_effects_app"], str(jsx)],
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError("After Effects launch failed: " + result.stderr.strip())


def send(resolve):
    cfg = settings()
    job = describe(resolve)
    base = Path(cfg["jobs_directory"]).expanduser()
    # Reopen an existing link instead of nesting a new composition around its render.
    for manifest in base.glob("*/job.json"):
        old = json.loads(manifest.read_text())
        if (Path(old["aep"]).is_file() and
                all(old.get(k) == job[k] for k in ("project_id", "timeline_id", "clip_id"))):
            start_worker(manifest, cfg)
            subprocess.run(["/usr/bin/open", "-a", cfg["after_effects_app"], old["aep"]], check=True)
            return manifest
    job_id = uuid.uuid4().hex[:12]
    directory = base / job_id
    directory.mkdir(parents=True, exist_ok=False)
    job.update(id=job_id, comp="Resolve Bridge " + job_id, aep=str(directory / "Composition.aep"),
               directory=str(directory), output_module=cfg["output_module"],
               applied_hash=None, auto_render=True, status="Opening After Effects")
    manifest = directory / "job.json"
    write_json(manifest, job)
    jsx = directory / "Open in After Effects.jsx"
    jsx.write_text(make_jsx(job), encoding="utf-8")
    try:
        launch_ae(cfg, jsx)
        if not Path(job["aep"]).exists() or not (directory / "ae-ready.txt").exists():
            raise RuntimeError("AE did not create the project. Check its dialog and scripting permissions.")
        start_worker(manifest, cfg)
    except Exception as exc:
        job["status"] = "Setup failed: " + str(exc)
        write_json(manifest, job)
        raise
    return manifest


def start_worker(manifest, cfg):
    (manifest.parent / "STOP").unlink(missing_ok=True)
    (manifest.parent / "RETRY").touch()
    with (manifest.parent / "bridge.log").open("a") as log:
        subprocess.Popen([cfg["python"], str(ROOT / "bridge.py"), "watch", str(manifest)],
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def connect():
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        candidates = [Path("/Applications/DaVinci Resolve.app"),
                      Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")]
        app = next((p for p in candidates if p.exists()), None)
        if not app:
            raise RuntimeError("Resolve installation not found.")
        os.environ["RESOLVE_SCRIPT_LIB"] = str(app / "Contents/Libraries/Fusion/fusionscript.so")
        sys.path.insert(0, str(app / "Contents/Resources/Developer/Scripting/Modules"))
        import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve unavailable. Keep Studio open and enable External scripting: Local.")
    return resolve


def fingerprint(path):
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (FileNotFoundError, PermissionError):
        return None


class SaveObserver:
    """Hash only after file metadata changes; do not reread large AEP files every poll."""
    def __init__(self):
        self.signature = None
        self.digest = None

    def read(self, path):
        try:
            stat = Path(path).stat()
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except OSError:
            self.signature, self.digest = None, None
            return None
        if signature != self.signature:
            self.digest = fingerprint(path)
            self.signature = signature if self.digest else None
        return self.digest


def find_target(resolve, job):
    manager, project, timeline = context(resolve)
    if project.GetUniqueId() != job["project_id"] or timeline.GetUniqueId() != job["timeline_id"]:
        raise RuntimeError("Update waiting: open the original project and timeline.")
    items = values(timeline.GetItemListInTrack("video", job["track"][1]))
    item = next((x for x in items if x.GetUniqueId() == job["clip_id"]), None)
    if not item:
        raise RuntimeError("Update waiting: original clip is missing or on a different track.")
    if number(item.GetStart()) != job["start"] or number(item.GetEnd()) != job["end"]:
        raise RuntimeError("Update paused: clip was moved or trimmed after linking.")
    media_id = item.GetMediaPoolItem().GetUniqueId()
    if media_id not in job["accepted_media_ids"]:
        raise RuntimeError("Update paused: the clip's source was changed outside the bridge.")
    expected_offset = job["offset"] if media_id == job["original_media_id"] else 0
    if abs(number(item.GetLeftOffset()) - expected_offset) > 0.001:
        raise RuntimeError("Update paused: the source range was slipped after linking.")
    if abs(number(item.GetProperty().get("Speed", 100)) - 100) > 0.001:
        raise RuntimeError("Update paused: clip speed changed after linking.")
    return manager, project, item


def apply_render(resolve, job, output):
    manager, project, item = find_target(resolve, job)
    imported = values(project.GetMediaPool().ImportMedia([str(output)]))
    if len(imported) != 1:
        raise RuntimeError("Resolve could not import the render.")
    media = imported[0]
    props = media.GetClipProperty()
    if abs(number(props["FPS"]) - job["fps"]) > 0.01 or int(number(props["Frames"])) != job["frames"]:
        raise RuntimeError("Render frame rate/duration changed. Restore the original AE composition timing.")
    previous = item.GetSelectedTakeIndex()
    if not item.AddTake(media, 0, job["frames"] - 1):
        raise RuntimeError("Resolve refused the new take; the original shot is unchanged.")
    index = item.GetTakesCount()
    if not item.SelectTakeByIndex(index):
        if previous:
            item.SelectTakeByIndex(previous)
        raise RuntimeError("Resolve could not select the rendered take.")
    # Do not finalize: retain original footage and all previous renders in Take Selector.
    job["accepted_media_ids"].append(media.GetUniqueId())
    return bool(manager.SaveProject())


def render(cfg, job, snapshot, output):
    import fcntl
    args = [cfg["aerender"], "-project", str(snapshot), "-comp", job["comp"],
            "-OMtemplate", cfg["output_module"], "-s", "0", "-e", str(job["frames"] - 1),
            "-output", str(output)]
    # All jobs in a library share a render lock, bounding AE memory/CPU usage.
    with (output.parent.parent / ".render.lock").open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if (output.parent / "STOP").exists():
                    raise RuntimeError("Stopped while waiting to render.")
                time.sleep(1)
        if (output.parent / "STOP").exists():
            raise RuntimeError("Stopped before rendering.")
        with output.with_suffix(".log").open("w") as log:
            result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=21600)
    if result.returncode or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("AE render failed. Check " + str(output.with_suffix(".log")) +
                           "; ensure output-module template '" + cfg["output_module"] + "' exists.")


def watch(manifest):
    import fcntl
    manifest = Path(manifest)
    # A lock per shot prevents duplicate workers after repeated menu clicks.
    with (manifest.parent / "worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        lock.write(str(os.getpid()))
        lock.flush()
        cfg = settings()
        job = json.loads(manifest.read_text())
        last_seen, stable_since, last_activity = None, time.monotonic(), time.monotonic()
        failed = None
        observer = SaveObserver()
        while time.monotonic() - last_activity < 8 * 3600:
            if (manifest.parent / "STOP").exists():
                break
            if (manifest.parent / "RETRY").exists():
                (manifest.parent / "RETRY").unlink(missing_ok=True)
                failed = None
            current = observer.read(job["aep"])
            if current != last_seen:
                last_seen, stable_since = current, time.monotonic()
                last_activity = time.monotonic()
            if current and current != job.get("applied_hash") and current != failed and time.monotonic() - stable_since >= 3:
                try:
                    pending = job.get("pending")
                    if not pending or pending["hash"] != current:
                        version = uuid.uuid4().hex[:10]
                        snapshot = manifest.parent / ("saved-" + version + ".aep")
                        shutil.copy2(job["aep"], snapshot)
                        if fingerprint(snapshot) != current:
                            snapshot.unlink()
                            continue
                        output = manifest.parent / ("render-" + version + ".mov")
                        job["status"] = "Rendering saved composition"
                        write_json(manifest, job)
                        try:
                            render(cfg, job, snapshot, output)
                        except Exception:
                            failed = current
                            raise
                        finally:
                            snapshot.unlink(missing_ok=True)
                        if fingerprint(job["aep"]) != current:
                            continue  # New save arrived during rendering. Do not apply stale output.
                        job["pending"] = dict(hash=current, output=str(output))
                        write_json(manifest, job)
                    if (manifest.parent / "STOP").exists():
                        break
                    if fingerprint(job["aep"]) != current:
                        continue
                    saved = apply_render(connect(), job, job["pending"]["output"])
                    job["applied_hash"] = current
                    job.pop("pending", None)
                    job["status"] = ("Updated in Resolve and project saved" if saved else
                                     "Take updated; Resolve could not save the project. Save it manually.")
                    LOG.info(job["status"])
                except Exception as exc:
                    job["status"] = str(exc)
                    job["last_error"] = str(exc)
                    LOG.warning("%s", exc)
                write_json(manifest, job)
            time.sleep(3)
        job["status"] = "Watcher stopped. Run Resume AE Updates to restart."
        write_json(manifest, job)


def resume():
    cfg = settings()
    for manifest in Path(cfg["jobs_directory"]).expanduser().glob("*/job.json"):
        if Path(json.loads(manifest.read_text())["aep"]).is_file():
            (manifest.parent / "STOP").unlink(missing_ok=True)
            start_worker(manifest, cfg)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) == 3 and sys.argv[1] == "watch":
        watch(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "resume":
        resume()
    else:
        print("Use Resolve's Replace with After Effects Composition script, or: bridge.py resume")
