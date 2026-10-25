/* Installed in After Effects' File > Scripts menu; also loaded by the Resolve handoff. */
var ResolveAEBridge = (function () {
    function ensureOutputTemplate(name) {
        var comp = app.project.items.addComp("Bridge output setup", 16, 16, 1, 1, 24);
        var queue = null;
        try {
            queue = app.project.renderQueue.items.add(comp);
            var names = queue.outputModule(1).templates;
            var ordered = [], i;
            for (i = 0; i < names.length; i++) {
                if (names[i] === name) { ordered.unshift(names[i]); }
                else if (/prores|high quality|lossless/i.test(names[i])) { ordered.push(names[i]); }
            }
            for (i = 0; i < ordered.length; i++) {
                try {
                    queue.outputModule(1).applyTemplate(ordered[i]);
                    var settings = queue.outputModule(1).getSettings(GetSettingsFormat.STRING);
                    // Format/codec cannot be set reliably through scripting. Reuse a real MOV preset.
                    if (!/quicktime/i.test(String(settings["Format"]))) { continue; }
                    queue.outputModule(1).saveAsTemplate(name);
                    app.preferences.saveToDisk();
                    return name;
                } catch (ignored) {}
            }
            throw new Error("No compatible QuickTime output template found. In Render Queue, save a QuickTime / ProRes template named '" + name + "', without resize or crop, then run the Resolve command again.");
        } finally {
            if (queue) { queue.remove(); }
            comp.remove();
        }
    }
    function showPanel() {
        var win = new Window("palette", "Resolve AE Bridge");
        win.orientation = "column";
        win.alignChildren = "fill";
        win.add("statictext", undefined, "Animate your linked composition, then press Cmd+S.");
        win.add("statictext", undefined, "The background render returns to the same Resolve shot.");
        var status = win.add("statictext", undefined, "");
        var save = win.add("button", undefined, "Save linked project");
        save.onClick = function () {
            if (!app.project.file || !new File(app.project.file.parent.fsName + "/job.json").exists) {
                status.text = "Open a project created by the Resolve bridge first.";
                return;
            }
            app.project.save();
            status.text = "Saved. The Resolve watcher will render this version.";
        };
        win.add("statictext", undefined, "Keep the generated project path and composition timing.");
        win.show();
        $._resolveBridgePanel = win;
    }
    return { ensureOutputTemplate: ensureOutputTemplate, showPanel: showPanel };
}());
if (!$._resolveBridgeHeadless) { ResolveAEBridge.showPanel(); }
