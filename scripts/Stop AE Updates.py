from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "Library/Application Support/Resolve AE Bridge/plugin"))
import bridge
count = bridge.stop()
print("Resolve AE Bridge: stop requested for %d link(s). Any running render will finish first." % count)
