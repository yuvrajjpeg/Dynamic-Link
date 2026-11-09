"""Exercise real polling, locks, snapshots and renderer subprocesses with simulated hosts.

This tests orchestration, not AE pixels or Resolve's native scripting compatibility.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

BRIDGE = Path(__file__).resolve().parents[1] / "resolve_ae"


class WorkerProcessTests(unittest.TestCase):
    def test_saves_supersede_and_pending_output_survives_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shot = base / "shot with spaces"
            shot.mkdir()
            aep = shot / "Composition.aep"
            aep.write_bytes(b"first save")
            renderer = base / "fake renderer"
            renderer.write_text("#!" + sys.executable + "\n" + '''
import pathlib, sys, time
args = sys.argv
snapshot = pathlib.Path(args[args.index('-project') + 1])
output = pathlib.Path(args[args.index('-output') + 1])
version = snapshot.read_bytes()
with (output.parent / 'rendered.txt').open('ab') as f:
    f.write(version + b'\\n')
if version == b'second save':
    (output.parent / 'render-started').touch()
    deadline = time.monotonic() + 15
    while not (output.parent / 'release-render').exists():
        if time.monotonic() > deadline: sys.exit(2)
        time.sleep(0.02)
output.write_bytes(version)
''')
            renderer.chmod(0o755)
            cfg = {"aerender": str(renderer), "output_module": "Fixture", "poll_seconds": 0.1,
                   "settle_seconds": 0.1}
            job = dict(aep=str(aep), comp="Linked", frames=10, fps=24, track=["video", 1],
                       start=100, end=110, offset=0, project_id="project", timeline_id="timeline",
                       clip_id="clip", original_media_id="source", accepted_media_ids=["source"],
                       applied_hash=None, auto_render=True)
            manifest = shot / "job.json"
            manifest.write_text(json.dumps(job))
            harness = base / "worker.py"
            harness.write_text('import sys\nsys.path.insert(0, ' + repr(str(BRIDGE)) + ')\n' + '''
import bridge, json
from pathlib import Path
from unittest.mock import Mock
folder = Path(sys.argv[1])
bridge.settings = lambda: json.loads(sys.argv[2])
media = Mock()
media.GetUniqueId.return_value = 'source'
item = Mock()
item.GetUniqueId.return_value = 'clip'
item.GetStart.return_value = 100
item.GetEnd.return_value = 110
item.GetLeftOffset.return_value = 0
item.GetProperty.return_value = {'Speed': 100}
item.GetMediaPoolItem.side_effect = lambda: media
item.GetSelectedTakeIndex.return_value = 1
item.GetTakesCount.return_value = 2
item.AddTake.return_value = True
item.SelectTakeByIndex.return_value = True
timeline = Mock()
timeline.GetUniqueId.return_value = 'timeline'
timeline.GetItemListInTrack.return_value = [item]
project = Mock()
project.GetUniqueId.return_value = 'project'
project.GetCurrentTimeline.return_value = timeline
manager = Mock()
manager.GetCurrentProject.return_value = project
resolve = Mock()
resolve.GetProjectManager.return_value = manager
current_output = None
def import_media(paths):
    global media, current_output
    current_output = Path(paths[0])
    media = Mock()
    media.GetUniqueId.return_value = str(current_output)
    media.GetClipProperty.return_value = {'FPS': '24', 'Frames': '10'}
    return [media]
def save():
    with (folder / 'applied.txt').open('ab') as f:
        f.write(current_output.read_bytes() + b'\\n')
    return True
project.GetMediaPool().ImportMedia.side_effect = import_media
manager.SaveProject.side_effect = save
def connect():
    if (folder / 'offline').exists():
        raise RuntimeError('Resolve disconnected')
    return resolve
bridge.connect = connect
bridge.watch(folder / 'job.json')
''')
            log = (base / "worker.log").open("w+")
            worker = subprocess.Popen([sys.executable, str(harness), str(shot), json.dumps(cfg)],
                                      stdout=log, stderr=log)
            def wait_for(predicate):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    if worker.poll() is not None:
                        log.seek(0)
                        self.fail("Worker exited: " + log.read())
                    time.sleep(0.03)
                log.seek(0)
                self.fail("Timed out: " + log.read())
            def lines(name):
                path = shot / name
                return path.read_text().splitlines() if path.exists() else []
            try:
                wait_for(lambda: lines("applied.txt") == ["first save"])
                duplicate = subprocess.run([sys.executable, str(harness), str(shot), json.dumps(cfg)],
                                           capture_output=True, text=True, timeout=5)
                self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
                self.assertEqual((shot / "worker.lock").read_text(), str(worker.pid))
                aep.write_bytes(b"second save")
                wait_for(lambda: (shot / "render-started").exists())
                aep.write_bytes(b"third save")
                (shot / "release-render").touch()
                wait_for(lambda: lines("applied.txt") == ["first save", "third save"])
                (shot / "offline").touch()
                aep.write_bytes(b"fourth save")
                wait_for(lambda: json.loads(manifest.read_text()).get("status") == "Resolve disconnected")
                self.assertEqual(lines("applied.txt"), ["first save", "third save"])
                (shot / "offline").unlink()
                wait_for(lambda: lines("applied.txt") == ["first save", "third save", "fourth save"])
                self.assertEqual(lines("rendered.txt"), ["first save", "second save", "third save", "fourth save"])
                (shot / "STOP").touch()
                worker.wait(timeout=5)
                self.assertEqual(worker.returncode, 0)
                final = json.loads(manifest.read_text())
                self.assertNotIn("last_error", final)
                self.assertNotIn("pending", final)
                self.assertNotIn("worker_pid", final)
            finally:
                if worker.poll() is None:
                    worker.terminate()
                    worker.wait(timeout=5)
                log.close()
