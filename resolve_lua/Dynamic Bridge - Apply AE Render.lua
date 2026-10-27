-- Workspace > Scripts menu entry. Loads the shared Dynamic Bridge library installed beside it.
local home = os.getenv("HOME") or ""
local candidates = {
    (debug.getinfo(1, "S").source:match("^@(.*)/[^/]+$") or "") .. "/.dynamic-bridge/dynamic_bridge.lib",
    home .. "/Library/Application Support/Fusion/Scripts/Utility/.dynamic-bridge/dynamic_bridge.lib",
    home .. "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/.dynamic-bridge/dynamic_bridge.lib",
}
for _, path in ipairs(candidates) do
    local ok, bridge = pcall(dofile, path)
    if ok and type(bridge) == "table" then return bridge.run("apply", resolve) end
end
print("Dynamic Bridge: library not found")
os.execute("/usr/bin/osascript -e 'display alert \"Dynamic Bridge\" message \"Bridge files are missing. Run the installer again.\" as critical' >/dev/null 2>&1 &")
