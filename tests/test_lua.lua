-- Exercises resolve_lua/dynamic_bridge.lib against a fake Resolve. Run: lua tests/test_lua.lua
local root = arg[0]:match("^(.*)/tests/") or "."
local bridge = dofile(root .. "/resolve_lua/lib/dynamic_bridge.lua")
local tmp = os.tmpname(); os.remove(tmp); os.execute("mkdir -p " .. bridge.quote(tmp))
bridge.plugin, bridge.jobs = root .. "/resolve_ae", tmp .. "/jobs"
bridge.jobs_for_ae = bridge.jobs
local source = tmp .. "/shot 01 'final'.mov"
bridge.write(source, "video")
local opened = {}
bridge.open_in_ae = function(path) opened[#opened + 1] = path; return true end

local takes, imported = {}, {}
local render_frames = 48
local function media(path, frames) return {
    GetClipProperty = function() return { ["File Path"] = path, FPS = "24", Frames = tostring(frames) } end,
    GetUniqueId = function() return path end } end
local item = {
    GetUniqueId = function() return "clip:1" end, GetName = function() return "Shot 1" end,
    GetTrackTypeAndIndex = function() return { "video", 1 } end,
    GetMediaPoolItem = function() return media(source, 500) end,
    GetDuration = function() return 48 end, GetSourceStartFrame = function() return 72 end,
    GetSourceEndFrame = function() return 119 end, GetLeftOffset = function() return 72 end,
    GetStart = function() return 86400 end, GetEnd = function() return 86448 end,
    AddTake = function(_, m, a, b) takes[#takes + 1] = { m, a, b }; return true end,
    GetTakesCount = function() return #takes + 1 end, SelectTakeByIndex = function() return true end,
}
local timeline = { GetSelectedClips = function() return { item } end, GetUniqueId = function() return "tl" end,
    GetSettings = function() return { timelineFrameRate = "24" } end }
local project = { GetCurrentTimeline = function() return timeline end, GetUniqueId = function() return "proj" end,
    GetMediaPool = function() return { ImportMedia = function(_, paths)
        imported[#imported + 1] = paths[1]; return { media(paths[1], render_frames) } end } end }
local resolve = { GetProjectManager = function() return { GetCurrentProject = function() return project end } end }

local failures = 0
local function check(name, ok, detail)
    print((ok and "ok   " or "FAIL ") .. name .. (ok and "" or ("  -> " .. tostring(detail))))
    if not ok then failures = failures + 1 end
end
local function expect_error(fn, pattern)
    local ok, err = pcall(fn); return not ok and tostring(err):find(pattern) ~= nil, err
end

local msg = bridge.send(resolve)
local dir = tmp .. "/jobs/clip_1"
check("send exports job and opens AE", bridge.exists(dir .. "/job.json") and opened[1] == dir .. "/Open in After Effects.jsx", msg)
local jsx = bridge.read(dir .. "/Open in After Effects.jsx")
check("handoff inlines job JSON", jsx:find('"offset":72', 1, true) and not jsx:find("/*BRIDGE_JOB*/null", 1, true), jsx:sub(1, 80))
check("source path with quote and space survives", jsx:find("shot 01 'final'.mov", 1, true) ~= nil)
check("pending handoff note written", bridge.read(tmp .. "/jobs/pending-handoff.txt") == dir .. "/Open in After Effects.jsx")
bridge.write(dir .. "/Composition.aep", "aep")
bridge.send(resolve)
check("second send reopens linked project", opened[2] == dir .. "/Composition.aep", opened[2])

check("apply before render explains next step", expect_error(function() bridge.apply(resolve) end, "No render yet"))
local render = dir .. "/render-1.mov"; bridge.write(render, "movie"); bridge.write(dir .. "/latest-render.txt", render .. "\n")
msg = bridge.apply(resolve)
check("apply adds take 0..47", #takes == 1 and takes[1][2] == 0 and takes[1][3] == 47, msg)
check("re-apply is a no-op", bridge.apply(resolve):find("already") ~= nil and #imported == 1)
local render2 = dir .. "/render-2.mov"; bridge.write(render2, "movie"); bridge.write(dir .. "/latest-render.txt", render2)
render_frames = 50
check("wrong-length render rejected, no take", expect_error(function() bridge.apply(resolve) end, "50 frames") and #takes == 1)

item.GetStart = function() return 86410 end
check("moved clip refused", expect_error(function() bridge.apply(resolve) end, "moved or trimmed"))
timeline.GetSelectedClips = function() return { item, item } end
check("two selected clips refused", expect_error(function() bridge.send(resolve) end, "exactly one"))
check("json escapes control chars", bridge.json({ a = 'q"\\\n' }) == '{"a":"q\\"\\\\\\n"}', bridge.json({ a = 'q"\\\n' }))

os.execute("rm -rf " .. bridge.quote(tmp))
print(failures == 0 and "ALL PASSED" or (failures .. " FAILED"))
os.exit(failures == 0 and 0 or 1)
