from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / "Library/Application Support/Resolve AE Bridge/plugin"))
import bridge

try:
    result = bridge.send(resolve)
    print("Resolve AE Bridge: " + str(result))
except Exception as error:
    print("Resolve AE Bridge: " + str(error))
    import subprocess
    subprocess.run(["/usr/bin/osascript", "-e",
                    'on run argv\ndisplay dialog (item 1 of argv) with title "Resolve AE Bridge" buttons {"OK"} default button "OK"\nend run',
                    str(error)])
