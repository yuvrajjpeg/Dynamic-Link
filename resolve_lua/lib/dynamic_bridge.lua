-- Dynamic Bridge for DaVinci Resolve, Lua edition.
-- The free and Mac App Store editions list only Lua scripts in Workspace > Scripts and cannot
-- be driven from outside, so this side runs entirely inside Resolve: it exports the shot for
-- After Effects and, on request, places the newest AE render back on the clip as a take.
local M = {}

local function script_path()
    local source = debug.getinfo(1, "S").source
    return source:sub(1, 1) == "@" and source:sub(2) or source
end

M.windows = package.config:sub(1, 1) == "\\"

-- macOS: the App Store edition is sandboxed. HOME is its container, whose Movies folder links to
-- ~/Movies, the only user folder it may write. Resolve writes through that link; After Effects
-- is handed the real path, since macOS asks before other apps read a container.
-- Windows: jobs live in %USERPROFILE%\Videos; forward slashes work for Lua and After Effects.
local home
if M.windows then
    home = (os.getenv("USERPROFILE") or ""):gsub("\\", "/")
else
    home = os.getenv("HOME") or ""
end
M.real_home = home:match("^(.-)/Library/Containers/") or home
M.plugin = (script_path():gsub("\\", "/")):match("^(.*)/[^/]+$") or "."
local media_folder = M.windows and "/Videos" or "/Movies"
M.jobs = home .. media_folder .. "/Resolve AE Bridge"
M.jobs_for_ae = M.real_home .. media_folder .. "/Resolve AE Bridge"
M.ae_bundle = "com.adobe.AfterEffects"

local VIDEO = { mov = true, mp4 = true, mxf = true, avi = true, m4v = true, mts = true, m2ts = true }

function M.number(value)
    local n = tonumber(tostring(value):match("%-?%d+%.?%d*"))
    if not n then error("Cannot read numeric value: " .. tostring(value), 0) end
    return n
end

function M.quote(text)
    if M.windows then return '"' .. tostring(text):gsub("/", "\\") .. '"' end  -- Windows paths cannot contain "
    return "'" .. tostring(text):gsub("'", "'\\''") .. "'"
end

function M.mkdir(dir)
    if M.windows then
        os.execute("mkdir " .. M.quote(dir) .. " 2>nul")
    else
        os.execute("/bin/mkdir -p " .. M.quote(dir))
    end
end

local function succeeded(status)
    return status == 0 or status == true  -- LuaJIT returns the exit code, Lua 5.2+ returns a boolean
end

-- Newest installed After Effects on Windows, by version year in its folder name.
function M.after_effects_exe()
    local base = (os.getenv("ProgramW6432") or os.getenv("ProgramFiles") or "C:\\Program Files") .. "\\Adobe"
    local pipe = io.popen('dir /b /ad "' .. base .. '\\Adobe After Effects*" 2>nul')
    local best, best_year = nil, -1
    for name in (pipe and pipe:lines() or function() end) do
        local exe = base .. "\\" .. name .. "\\Support Files\\AfterFX.exe"
        local year = tonumber(name:match("(%d%d%d%d)")) or 0
        if M.exists(exe) and year > best_year then best, best_year = exe, year end
    end
    if pipe then pipe:close() end
    return best
end

function M.read(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local text = f:read("*a")
    f:close()
    return text
end

function M.write(path, text)
    local f, err = io.open(path, "w")
    if not f then error("Cannot write " .. path .. ": " .. tostring(err), 0) end
    f:write(text)
    f:close()
end

function M.exists(path)
    local f = io.open(path, "r")
    if f then f:close() return true end
    return false
end

local function escape(s)
    return (s:gsub('[%c"\\]', function(c)
        local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
        return map[c] or string.format("\\u%04x", c:byte())
    end))
end

function M.json(value)
    local kind = type(value)
    if kind == "string" then return '"' .. escape(value) .. '"' end
    if kind == "number" then
        return value == math.floor(value) and string.format("%d", value) or string.format("%.6f", value)
    end
    if kind == "boolean" then return tostring(value) end
    if kind == "table" then
        local keys = {}
        for k in pairs(value) do keys[#keys + 1] = k end
        table.sort(keys)
        local parts = {}
        for _, k in ipairs(keys) do parts[#parts + 1] = M.json(tostring(k)) .. ":" .. M.json(value[k]) end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return "null"
end

local function list(items)
    local out = {}
    for _, v in pairs(items or {}) do out[#out + 1] = v end
    return out
end

local function timeline_fps(timeline)
    local ok, settings = pcall(function() return timeline:GetSettings() end)
    if ok and type(settings) == "table" and settings.timelineFrameRate then return settings.timelineFrameRate end
    return timeline:GetSetting("timelineFrameRate")
end

function M.context(resolve)
    local project = resolve:GetProjectManager():GetCurrentProject()
    local timeline = project and project:GetCurrentTimeline()
    if not timeline then error("Open a project and timeline first.", 0) end
    return project, timeline
end

function M.current_clip(timeline)
    local video = {}
    local ok, selected = pcall(function() return timeline:GetSelectedClips() end)
    for _, item in ipairs(ok and list(selected) or {}) do
        if item:GetTrackTypeAndIndex()[1] == "video" then video[#video + 1] = item end
    end
    if #video > 1 then error("Select exactly one video clip.", 0) end
    local item = video[1] or timeline:GetCurrentVideoItem()
    if not item then error("Select a video clip or put the playhead over one.", 0) end
    return item
end

function M.describe(resolve)
    local project, timeline = M.context(resolve)
    local item = M.current_clip(timeline)
    local media = item:GetMediaPoolItem()
    if not media then error("Choose an ordinary video file, not a generator or compound clip.", 0) end
    local props = media:GetClipProperty()
    local source = props["File Path"] or ""
    local ext = (source:match("%.([%w]+)$") or ""):lower()
    -- No existence check: the sandbox cannot read most media folders, but Resolve already can.
    if source == "" or not VIDEO[ext] then
        error("This version supports ordinary video files; compound, multicam, RAW and image sequences are unsupported.", 0)
    end
    local fps = M.number(timeline_fps(timeline))
    if math.abs(M.number(props["FPS"]) - fps) > 0.01 then
        error("Source and timeline frame rates must match in this version.", 0)
    end
    local duration = M.number(item:GetDuration())
    local first, last = M.number(item:GetSourceStartFrame()), M.number(item:GetSourceEndFrame())
    if math.abs((last - first + 1) - duration) > 0.05 then
        error("Retimed, reversed or freeze-frame clips are unsupported. Use an ordinary 100% speed shot.", 0)
    end
    local offset = M.number(item:GetLeftOffset())
    if duration <= 0 or offset < 0 or math.abs(duration - math.floor(duration + 0.5)) > 0.001 then
        error("Invalid or fractional clip range.", 0)
    end
    local track = item:GetTrackTypeAndIndex()
    local id = item:GetUniqueId()
    return {
        id = id:gsub("[^%w%-]", "_"), clip_id = id, project_id = project:GetUniqueId(),
        timeline_id = timeline:GetUniqueId(), name = item:GetName(), source = source,
        fps = fps, frames = math.floor(duration + 0.5), offset = offset,
        start = M.number(item:GetStart()), ["end"] = M.number(item:GetEnd()), track = track[2],
    }, item, project
end

function M.job_dir(id)
    return M.jobs .. "/" .. id
end

function M.handoff_jsx(job)
    local companion = M.read(M.plugin .. "/Resolve AE Bridge.jsx")
    local template = M.read(M.plugin .. "/create_composition.jsx")
    if not companion or not template then error("Bridge files are missing from " .. M.plugin .. ". Run the installer again.", 0) end
    local marker = "/*BRIDGE_JOB*/null"
    local at = template:find(marker, 1, true)
    template = template:sub(1, at - 1) .. M.json(job) .. template:sub(at + #marker)
    return "$._resolveBridgeHeadless = true;\ntry {\n" .. companion .. "\n" .. template ..
           "\n} finally { $._resolveBridgeHeadless = false; }\n"
end

-- Opens a project, or runs a .jsx script, in After Effects. False when After Effects is missing.
function M.open_in_ae(path)
    if not M.windows then
        if path:lower():match("%.jsx$") then
            -- Opening a JSX as a document does not execute it. Pass the path as an argv
            -- value to JXA, so spaces, quotes and Unicode never become executable code.
            local script = 'function run(argv) { var ae = Application("com.adobe.AfterEffects"); ae.activate(); ae.doscriptfile(argv[0]); }'
            local log = M.jobs .. "/ae-launch.log"
            local ok = succeeded(os.execute("/usr/bin/osascript -l JavaScript -e " .. M.quote(script) ..
                " " .. M.quote(path) .. " >" .. M.quote(log) .. " 2>&1"))
            if ok then return true end
            error("Automatic After Effects handoff failed. Check " .. log ..
                ". In After Effects choose File > Scripts > Resolve AE Bridge > Open shot from Resolve. " ..
                "If the companion is missing, use File > Scripts > Run Script File and choose " .. path ..
                ". Install After Effects first if it is missing.", 0)
        end
        return succeeded(os.execute("/usr/bin/open -b " .. M.ae_bundle .. " " .. M.quote(path)))
    end
    local exe = M.after_effects_exe()
    if not exe then return false end
    local flag = path:lower():match("%.jsx$") and "-r " or ""  -- AfterFX.exe -r runs a script file
    return succeeded(os.execute('start "" ' .. M.quote(exe) .. " " .. flag .. M.quote(path)))
end

function M.send(resolve)
    local job = M.describe(resolve)
    local dir = M.job_dir(job.id)
    local ae_dir = M.jobs_for_ae .. "/" .. job.id
    local aep = dir .. "/Composition.aep"
    M.mkdir(dir)
    if M.exists(aep) then
        M.write(M.jobs .. "/pending-handoff.txt", ae_dir .. "/Open in After Effects.jsx")
        if not M.open_in_ae(ae_dir .. "/Composition.aep") then
            error("After Effects is not installed, so the linked project cannot open.", 0)
        end
        return "Reopened the linked After Effects project for \"" .. job.name .. "\".\n\n" ..
               "When the animation is ready, click Render for Resolve in the After Effects panel."
    end
    job.comp = "Resolve Bridge " .. job.id:sub(1, 12)
    job.aep, job.directory, job.output_module = ae_dir .. "/Composition.aep", ae_dir, "Resolve Bridge ProRes"
    M.write(dir .. "/job.json", M.json(job))
    M.write(dir .. "/Open in After Effects.jsx", M.handoff_jsx(job))
    M.write(M.jobs .. "/pending-handoff.txt", ae_dir .. "/Open in After Effects.jsx")
    if not M.open_in_ae(ae_dir .. "/Open in After Effects.jsx") then
        error("The shot was exported to\n" .. ae_dir .. "\n\nbut After Effects is not installed. " ..
              "Install it, then run Send to After Effects again.", 0)
    end
    return "Sent \"" .. job.name .. "\" to After Effects.\n\n" ..
           "If After Effects does not build the composition by itself, open File > Scripts > Resolve AE Bridge " ..
           "and click Open shot from Resolve.\n\nAnimate, click Render for Resolve, then run Apply AE Render here."
end

function M.apply(resolve)
    local project, timeline = M.context(resolve)
    local item = M.current_clip(timeline)
    local dir = M.job_dir(item:GetUniqueId():gsub("[^%w%-]", "_"))
    local manifest = M.read(dir .. "/job.json")
    if not manifest then error("This clip has not been sent to After Effects yet. Run Send to After Effects first.", 0) end
    local latest = (M.read(dir .. "/latest-render.txt") or ""):gsub("^\239\187\191", ""):gsub("%s+$", "")
    -- After Effects records the real path; read it back through the App Store edition's Movies link.
    local readable = latest:sub(1, #M.jobs_for_ae) == M.jobs_for_ae and M.jobs .. latest:sub(#M.jobs_for_ae + 1) or latest
    if latest == "" or not M.exists(readable) then
        error("No render yet. In After Effects, click Render for Resolve in the bridge panel.", 0)
    end
    if (M.read(dir .. "/applied.txt") or ""):gsub("%s+$", "") == latest then
        return "The newest After Effects render is already on this clip."
    end
    local start, frames = manifest:match('"start":(%-?[%d%.]+)'), manifest:match('"frames":(%d+)')
    if M.number(item:GetStart()) ~= M.number(start) or M.number(item:GetDuration()) ~= M.number(frames) then
        error("The clip was moved or trimmed after it was sent. Undo that change, then apply again.", 0)
    end
    local imported = list(project:GetMediaPool():ImportMedia({ latest }))
    if #imported ~= 1 then error("Resolve could not import " .. latest, 0) end
    local media = imported[1]
    local props = media:GetClipProperty()
    local fps = manifest:match('"fps":%s*([%d%.]+)')
    if not fps or math.abs(M.number(props["FPS"]) - M.number(fps)) > 0.01 then
        error("The render frame rate differs from the linked clip. Restore the original composition frame rate.", 0)
    end
    if math.floor(M.number(props["Frames"]) + 0.5) ~= M.number(frames) then
        error("The render is " .. tostring(props["Frames"]) .. " frames, but the clip is " .. frames ..
              ". Keep the composition length unchanged in After Effects.", 0)
    end
    if not item:AddTake(media, 0, M.number(frames) - 1) then error("Resolve refused the new take; the clip is unchanged.", 0) end
    if not item:SelectTakeByIndex(item:GetTakesCount()) then error("Resolve added the take but could not select it.", 0) end
    M.write(dir .. "/applied.txt", latest)
    return "Placed the newest After Effects render on \"" .. item:GetName() .. "\" as a new take.\n\n" ..
           "The original and earlier renders stay in the Take Selector."
end

-- Resolve Free blocks script windows (UIManager) since 19.1, so results go to a system alert,
-- Workspace > Console and a log file beside the jobs.
function M.log(text)
    M.mkdir(M.jobs)
    local f = io.open(M.jobs .. "/resolve-log.txt", "a")
    if f then f:write(os.date("%Y-%m-%d %H:%M:%S "), text, "\n") f:close() end
end

function M.show(message, failed)
    print("Dynamic Bridge: " .. message)
    if M.windows then
        -- The message travels through a file so no quoting rule of cmd or PowerShell can break it.
        local text = (os.getenv("TEMP") or ".") .. "\\dynamic-bridge-message.txt"
        local ok = pcall(M.write, text, message)
        if ok then
            os.execute('start "" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "' ..
                "Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show(" ..
                "[IO.File]::ReadAllText('" .. text:gsub("'", "''") .. "'), 'Dynamic Bridge', 'OK', '" ..
                (failed and "Warning" or "Information") .. "')\"")
        end
        return
    end
    os.execute("/usr/bin/osascript -e 'on run argv' -e 'activate' -e 'display alert (item 1 of argv) message (item 2 of argv)" ..
               (failed and " as critical" or "") .. "' -e 'end run' " .. M.quote("Dynamic Bridge") .. " " ..
               M.quote(message) .. " >/dev/null 2>&1 &")
end

function M.run(action, resolve)
    if not resolve and type(Resolve) == "function" then resolve = Resolve() end
    if not resolve and bmd and bmd.scriptapp then resolve = bmd.scriptapp("Resolve") end
    pcall(M.log, action .. " started. HOME=" .. home .. (resolve and "" or " (no resolve object)"))
    local ok, result = pcall(M[action], resolve)
    pcall(M.log, (ok and "ok: " or "error: ") .. tostring(result):gsub("\n", " "))
    M.show(ok and result or ("Could not finish: " .. tostring(result)), not ok)
end

return M
