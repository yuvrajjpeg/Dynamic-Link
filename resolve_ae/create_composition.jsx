/* Executed inside After Effects. Only creates a dedicated project after saving existing work. */
(function () {
    var job = /*BRIDGE_JOB*/null;
    try {
        if (app.project && (app.project.numItems > 0 || app.project.file)) {
            // AE owns the Save/Discard/Cancel prompt; cancel leaves the current project open.
            if (!app.project.close(CloseOptions.PROMPT_TO_SAVE_CHANGES)) {
                throw new Error("Cancelled; existing After Effects project was kept open.");
            }
        }
        app.newProject();
        if (job.auto_render) { ResolveAEBridge.ensureOutputTemplate(job.output_module || "Resolve Bridge ProRes"); }
        var footage = app.project.importFile(new ImportOptions(new File(job.source)));
        if (!footage.hasVideo) { throw new Error("Source has no video."); }
        var duration = job.frames / job.fps;
        // Native source dimensions preserve Resolve's existing sizing when used as a take.
        var comp = app.project.items.addComp(job.comp, footage.width, footage.height,
                                            footage.pixelAspect, duration, job.fps);
        comp.displayStartTime = 0;
        comp.workAreaStart = 0;
        comp.workAreaDuration = duration;
        var layer = comp.layers.add(footage);
        layer.startTime = -job.offset / job.fps;
        layer.inPoint = 0;
        layer.outPoint = duration;
        layer.audioEnabled = false; // Existing Resolve audio remains on the timeline.
        comp.comment = "Resolve AE Bridge: " + job.id + ". Keep name, duration and frame rate unchanged.";
        comp.openInViewer();
        app.project.save(new File(job.aep));
        var ready = new File(job.directory + "/ae-ready.txt");
        if (!ready.open("w")) { throw new Error("Cannot write bridge readiness file."); }
        ready.write("ready");
        ready.close();
    } catch (error) {
        alert("Resolve AE Bridge: " + error.toString());
        throw error;
    }
}());
