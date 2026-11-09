from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / "Library/Application Support/Resolve AE Bridge/plugin"))
import bridge
count = bridge.resume()
print("Resolve AE Bridge: resumed %d background link(s). View status in each job.json / bridge.log." % count)
