from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "Library/Application Support/Resolve AE Bridge/plugin"))
import bridge
cfg = bridge.settings()
for manifest in Path(cfg["jobs_directory"]).expanduser().glob("*/job.json"):
    (manifest.parent / "STOP").touch()
print("Resolve AE Bridge: stop requested. Any running render will finish first.")
