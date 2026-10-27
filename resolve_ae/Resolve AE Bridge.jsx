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
    function readText(file) {
        file.encoding = "UTF-8";
        if (!file.open("r")) { throw new Error("Cannot read " + file.fsName); }
        var text = file.read();
        file.close();
        return text;
    }
    function writeText(file, text) {
        file.encoding = "UTF-8";
        if (!file.open("w")) { throw new Error("Cannot write " + file.fsName); }
        file.write(text);
        file.close();
    }
    function linkedJob() {
        var manifest = app.project.file && new File(app.project.file.parent.fsName + "/job.json");
        if (!manifest || !manifest.exists) { throw new Error("Open a project created by Dynamic Bridge first."); }
        // ExtendScript has no JSON object; the manifest is written by the bridge itself.
        return eval("(" + readText(manifest) + ")");
    }
    // Free and App Store Resolve cannot reach After Effects, so Send to After Effects leaves a note here.
    function openFromResolve() {
        var pending = new File(Folder.myDocuments.parent.fsName + "/Movies/Resolve AE Bridge/pending-handoff.txt");
        if (!pending.exists) { throw new Error("Nothing to open. In Resolve, run Dynamic Bridge - Send to After Effects first."); }
        var handoff = new File(readText(pending).replace(/\s+$/, ""));
        var aep = new File(handoff.parent.fsName + "/Composition.aep");
        if (aep.exists) { app.open(aep); }
        else if (handoff.exists) { $.evalFile(handoff); }
        else { throw new Error("The exported shot is missing: " + handoff.fsName); }
        pending.remove();
        return "Opened the linked composition.";
    }
    function renderForResolve() {
        var job = linkedJob(), comp = null, i;
        app.project.save();
        for (i = 1; i <= app.project.numItems; i++) {
            if (app.project.item(i) instanceof CompItem && app.project.item(i).name === job.comp) { comp = app.project.item(i); }
        }
        if (!comp) { throw new Error("Composition '" + job.comp + "' is missing. Keep its name unchanged."); }
        // Render only this composition: park anything else the user has queued.
        var queue = app.project.renderQueue, parked = [], item;
        for (i = 1; i <= queue.numItems; i++) {
            if (queue.item(i).status === RQItemStatus.QUEUED) { parked.push(queue.item(i)); queue.item(i).render = false; }
        }
        item = queue.items.add(comp);
        var output = new File(job.directory + "/render-" + new Date().getTime() + ".mov");
        try {
            item.outputModule(1).applyTemplate(job.output_module || "Resolve Bridge ProRes");
            item.outputModule(1).file = output;
            queue.render();
        } finally {
            item.remove();
            for (i = 0; i < parked.length; i++) { parked[i].render = true; }
        }
        if (!output.exists) { throw new Error("After Effects did not write " + output.fsName); }
        writeText(new File(job.directory + "/latest-render.txt"), output.fsName);
        return "Rendered. In Resolve, select the clip and run Dynamic Bridge - Apply AE Render.";
    }
    function showPanel() {
        var win = new Window("palette", "Dynamic Bridge");
        win.orientation = "column";
        win.alignChildren = "fill";
        win.add("statictext", undefined, "1. Open the shot you sent from Resolve.");
        var open = win.add("button", undefined, "Open shot from Resolve");
        win.add("statictext", undefined, "2. Animate, then render it back.");
        var render = win.add("button", undefined, "Render for Resolve");
        var status = win.add("statictext", undefined, "Keep the composition name and length unchanged.", {multiline: true});
        status.preferredSize = [320, 40];
        function run(action) {
            try { status.text = action(); } catch (error) { status.text = error.message || String(error); }
        }
        open.onClick = function () { run(openFromResolve); };
        render.onClick = function () { run(renderForResolve); };
        win.show();
        $._resolveBridgePanel = win;
    }
    return { ensureOutputTemplate: ensureOutputTemplate, showPanel: showPanel,
             openFromResolve: openFromResolve, renderForResolve: renderForResolve };
}());
if (!$._resolveBridgeHeadless) { ResolveAEBridge.showPanel(); }
