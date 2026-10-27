-- Exercises the Windows branch of resolve_lua/lib/dynamic_bridge.lua on any machine.
-- Run: USERPROFILE='C:\Users\Test' lua tests/test_lua_windows.lua
local root = arg[0]:match("^(.*)/tests/") or "."
package.config = "\\" .. package.config:sub(2)  -- make the library believe it runs on Windows
local bridge = dofile(root .. "/resolve_lua/lib/dynamic_bridge.lua")

local failures = 0
local function check(name, ok, detail)
    print((ok and "ok   " or "FAIL ") .. name .. (ok and "" or ("  -> " .. tostring(detail))))
    if not ok then failures = failures + 1 end
end

check("windows detected", bridge.windows)
check("jobs live in Videos", bridge.jobs == "C:/Users/Test/Videos/Resolve AE Bridge", bridge.jobs)
check("quote uses backslashes", bridge.quote("C:/a b/c.jsx") == '"C:\\a b\\c.jsx"', bridge.quote("C:/a b/c.jsx"))

-- Fake the Adobe folder listing and the file system; capture commands instead of running them.
local commands = {}
local real_popen, real_execute, real_exists = io.popen, os.execute, bridge.exists
io.popen = function(cmd)
    commands[#commands + 1] = cmd
    local names = { "Adobe After Effects CC 2019", "Adobe After Effects 2026", "Adobe After Effects 2025" }
    local i = 0
    return { lines = function() return function() i = i + 1; return names[i] end end, close = function() end }
end
os.execute = function(cmd) commands[#commands + 1] = cmd; return 0 end
bridge.exists = function() return true end

local exe = bridge.after_effects_exe()
check("newest After Effects chosen by year", exe and exe:find("Adobe After Effects 2026", 1, true), exe)
check("script runs with -r", bridge.open_in_ae("C:/Users/Test/Videos/Resolve AE Bridge/x/Open in After Effects.jsx")
    and commands[#commands]:find('AfterFX.exe" -r "C:\\Users\\Test\\Videos\\Resolve AE Bridge\\x\\Open in After Effects.jsx"', 1, true),
    commands[#commands])
bridge.open_in_ae("C:/jobs/x/Composition.aep")
check("project opens without -r", not commands[#commands]:find(" -r ", 1, true) and commands[#commands]:find('"C:\\jobs\\x\\Composition.aep"', 1, true),
    commands[#commands])
bridge.mkdir("C:/Users/Test/Videos/Resolve AE Bridge/x")
check("mkdir uses cmd syntax", commands[#commands] == 'mkdir "C:\\Users\\Test\\Videos\\Resolve AE Bridge\\x" 2>nul', commands[#commands])

io.popen = function() return nil end
check("missing After Effects reported", bridge.open_in_ae("C:/x.jsx") == false)

io.popen, os.execute, bridge.exists = real_popen, real_execute, real_exists
print(failures == 0 and "ALL PASSED" or (failures .. " FAILED"))
os.exit(failures == 0 and 0 or 1)
