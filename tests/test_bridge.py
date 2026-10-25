import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack

SPEC = importlib.util.spec_from_file_location("bridge", Path(__file__).parents[1] / "resolve_ae/bridge.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "shot's $(literal).mov"
        self.source.write_bytes(b"source")
        self.media = Mock()
        self.media.GetUniqueId.return_value = "source-id"
        self.media.GetClipProperty.return_value = {"File Path": str(self.source), "FPS": "24", "Frames": "100"}
        self.item = Mock()
        self.item.GetMediaPoolItem.return_value = self.media
        self.item.GetUniqueId.return_value = "clip-id"
        self.item.GetTrackTypeAndIndex.return_value = ["video", 1]
        self.item.GetDuration.return_value = 10
        self.item.GetSourceStartFrame.return_value = 20
        self.item.GetSourceEndFrame.return_value = 29
        self.item.GetLeftOffset.return_value = 20
        self.item.GetProperty.return_value = {"Speed": 100}
        self.item.GetStart.return_value = 86400
        self.item.GetEnd.return_value = 86410
        self.item.GetName.return_value = "Shot"
        self.item.GetSelectedTakeIndex.return_value = 1
        self.item.GetTakesCount.return_value = 2
        self.timeline = Mock()
        self.timeline.GetSelectedClips.return_value = [self.item]
        self.timeline.GetUniqueId.return_value = "timeline-id"
        self.timeline.GetSettings.return_value = {"timelineFrameRate": "24"}
        self.timeline.GetItemListInTrack.return_value = [self.item]
        self.project = Mock()
        self.project.GetUniqueId.return_value = "project-id"
        self.project.GetCurrentTimeline.return_value = self.timeline
        self.manager = Mock()
        self.manager.GetCurrentProject.return_value = self.project
        self.manager.SaveProject.return_value = True
        self.resolve = Mock()
        self.resolve.GetProjectManager.return_value = self.manager

    def test_trim_metadata_and_selected_clip(self):
        job = bridge.describe(self.resolve)
        self.assertEqual((job["offset"], job["frames"], job["fps"]), (20, 10, 24))
        self.timeline.GetCurrentVideoItem.assert_not_called()

    def test_multiple_selected_video_clips_rejected(self):
        self.timeline.GetSelectedClips.return_value = [self.item, self.item]
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            bridge.describe(self.resolve)

    def test_mixed_frame_rates_and_retimes_rejected(self):
        self.media.GetClipProperty.return_value["FPS"] = "30"
        with self.assertRaisesRegex(RuntimeError, "frame rates"):
            bridge.describe(self.resolve)
        self.media.GetClipProperty.return_value["FPS"] = "24"
        self.item.GetSourceEndFrame.return_value = 39
        with self.assertRaisesRegex(RuntimeError, "Retimed"):
            bridge.describe(self.resolve)

    def test_wrong_project_or_edited_clip_never_imports(self):
        job = bridge.describe(self.resolve)
        self.project.GetUniqueId.return_value = "other-project"
        with self.assertRaisesRegex(RuntimeError, "original project"):
            bridge.apply_render(self.resolve, job, "render.mov")
        self.project.GetMediaPool.assert_not_called()
        self.project.GetUniqueId.return_value = "project-id"
        self.item.GetLeftOffset.return_value = 21
        with self.assertRaisesRegex(RuntimeError, "slipped"):
            bridge.apply_render(self.resolve, job, "render.mov")

    def test_take_is_selected_without_finalizing_original(self):
        job = bridge.describe(self.resolve)
        rendered = Mock()
        rendered.GetClipProperty.return_value = {"FPS": "24", "Frames": "10"}
        rendered.GetUniqueId.return_value = "render-id"
        self.project.GetMediaPool().ImportMedia.return_value = [rendered]
        self.assertTrue(bridge.apply_render(self.resolve, job, "render.mov"))
        self.item.AddTake.assert_called_once_with(rendered, 0, 9)
        self.item.SelectTakeByIndex.assert_called_once_with(2)
        self.item.FinalizeTake.assert_not_called()
        self.assertIn("render-id", job["accepted_media_ids"])
        self.manager.SaveProject.assert_called_once()

    def test_wrong_render_length_does_not_change_take(self):
        job = bridge.describe(self.resolve)
        rendered = Mock()
        rendered.GetClipProperty.return_value = {"FPS": "24", "Frames": "11"}
        self.project.GetMediaPool().ImportMedia.return_value = [rendered]
        with self.assertRaisesRegex(RuntimeError, "duration changed"):
            bridge.apply_render(self.resolve, job, "render.mov")
        self.item.AddTake.assert_not_called()

    def test_failed_select_restores_previous_take(self):
        job = bridge.describe(self.resolve)
        rendered = Mock()
        rendered.GetClipProperty.return_value = {"FPS": "24", "Frames": "10"}
        self.project.GetMediaPool().ImportMedia.return_value = [rendered]
        self.item.SelectTakeByIndex.return_value = False
        with self.assertRaisesRegex(RuntimeError, "could not select"):
            bridge.apply_render(self.resolve, job, "render.mov")
        self.assertEqual(self.item.SelectTakeByIndex.call_args_list[-1].args, (1,))

    def test_render_failure_never_implies_output_success(self):
        cfg = {"aerender": "/fake/aerender", "output_module": "Resolve Bridge ProRes"}
        job = {"comp": "Composition", "frames": 10}
        out = Path(self.tmp.name) / "result.mov"
        with patch.object(bridge.subprocess, "run", return_value=Mock(returncode=1)) as run:
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                bridge.render(cfg, job, self.source, out)
        self.assertIn(str(self.source), run.call_args.args[0])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_jsx_metadata_is_json_escaped(self):
        job = {"source": str(self.source), "comp": 'quote"\\test'}
        jsx = bridge.make_jsx(job)
        self.assertIn(json.dumps(job, ensure_ascii=True), jsx)
        self.assertNotIn("/*BRIDGE_JOB*/null", jsx)

    def test_atomic_manifest_and_missing_file(self):
        manifest = Path(self.tmp.name) / "job.json"
        bridge.write_json(manifest, {"status": "ready"})
        self.assertEqual(json.loads(manifest.read_text())["status"], "ready")
        self.assertFalse(manifest.with_suffix(".json.tmp").exists())
        self.assertIsNone(bridge.fingerprint(manifest.parent / "absent.aep"))

    def test_idle_observer_hashes_once_then_detects_new_save(self):
        observer = bridge.SaveObserver()
        with patch.object(bridge, "fingerprint", wraps=bridge.fingerprint) as digest:
            first = observer.read(self.source)
            for _ in range(20):
                self.assertEqual(observer.read(self.source), first)
            self.assertEqual(digest.call_count, 1)
            self.source.write_bytes(b"changed saved project")
            self.assertNotEqual(observer.read(self.source), first)
            self.assertEqual(digest.call_count, 2)

    def watcher_fixture(self):
        directory = Path(self.tmp.name)
        aep = directory / "Composition.aep"
        aep.write_bytes(b"saved version one")
        job = bridge.describe(self.resolve)
        job.update(aep=str(aep), comp="Bridge", applied_hash=None)
        manifest = directory / "job.json"
        bridge.write_json(manifest, job)
        return directory, aep, manifest

    def test_save_during_render_only_applies_latest_version(self):
        directory, aep, manifest = self.watcher_fixture()
        rendered = []
        clock = iter(range(0, 1000, 4))

        def fake_render(cfg, job, snapshot, output):
            rendered.append(snapshot.read_bytes())
            output.write_bytes(b"movie")
            if len(rendered) == 1:
                aep.write_bytes(b"saved version two")

        with ExitStack() as stack:
            stack.enter_context(patch.object(bridge, "settings", return_value={}))
            stack.enter_context(patch.object(bridge.time, "monotonic", side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(bridge.time, "sleep", side_effect=lambda _: (directory / "STOP").touch()))
            stack.enter_context(patch.object(bridge, "render", side_effect=fake_render))
            stack.enter_context(patch.object(bridge, "connect", return_value=self.resolve))
            apply = stack.enter_context(patch.object(bridge, "apply_render", return_value=True))
            bridge.watch(manifest)
        self.assertEqual(rendered, [b"saved version one", b"saved version two"])
        apply.assert_called_once()
        self.assertEqual(json.loads(manifest.read_text())["applied_hash"], bridge.fingerprint(aep))

    def test_stop_during_render_does_not_place_output(self):
        directory, aep, manifest = self.watcher_fixture()
        clock = iter(range(0, 1000, 4))

        def fake_render(cfg, job, snapshot, output):
            output.write_bytes(b"movie")
            (directory / "STOP").touch()

        with ExitStack() as stack:
            stack.enter_context(patch.object(bridge, "settings", return_value={}))
            stack.enter_context(patch.object(bridge.time, "monotonic", side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(bridge, "render", side_effect=fake_render))
            apply = stack.enter_context(patch.object(bridge, "apply_render"))
            bridge.watch(manifest)
        apply.assert_not_called()
        self.assertIsNone(json.loads(manifest.read_text())["applied_hash"])

    def test_failed_render_never_updates_resolve(self):
        directory, aep, manifest = self.watcher_fixture()
        clock = iter(range(0, 1000, 4))
        with ExitStack() as stack:
            stack.enter_context(patch.object(bridge, "settings", return_value={}))
            stack.enter_context(patch.object(bridge.time, "monotonic", side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(bridge.time, "sleep", side_effect=lambda _: (directory / "STOP").touch()))
            stack.enter_context(patch.object(bridge, "render", side_effect=RuntimeError("render failed")))
            apply = stack.enter_context(patch.object(bridge, "apply_render"))
            with self.assertLogs(bridge.LOG, level="WARNING"):
                bridge.watch(manifest)
        apply.assert_not_called()
        self.assertIsNone(json.loads(manifest.read_text())["applied_hash"])


if __name__ == "__main__":
    unittest.main()
