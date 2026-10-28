# Resolve → After Effects Bridge

## Windows update (0.1.2)

Use `dist/Dynamic Bridge Setup.exe`. Close both apps before installing, then restart them. The installer now places Resolve scripts in the documented all-users ProgramData directory, with the shared library alongside them. It also refreshes an existing per-user library for the account running setup. If an older installation belongs to a different Windows account, uninstall that old per-user copy from that account first so it cannot shadow the new scripts.

The AE panel now uses USERPROFILE to find pending handoffs, including when Documents is redirected to OneDrive. Manual renders accept compatible AVI presets as well as QuickTime and use the matching file extension. Existing named templates are reused without attempting to overwrite them.

Enable **Allow Scripts to Write Files and Access Network** in AE. Test a short, ordinary video clip with matching source/timeline FPS: **Send to After Effects**, then **File → Scripts → Resolve AE Bridge → Render for Resolve**, then **Apply AE Render** in Resolve. If either action fails, capture its exact message and `%USERPROFILE%\Videos\Resolve AE Bridge\resolve-log.txt`, along with both application versions. Custom AE installation locations are not auto-detected by the Windows launcher; use AE's **Run Script File** on the exported handoff JSX in that case.

Windows branches and AE behavior are covered by simulated tests; a native Windows round trip has not been verified here.

## Button fixes (0.1.1)

The manual workflow is **Send to After Effects** in Resolve → **Render for Resolve** in AE's **File → Scripts → Resolve AE Bridge** panel → **Apply AE Render** in Resolve. Install the updated package and restart both apps. After Effects must be installed separately.

The macOS launcher now explicitly executes the handoff with JXA, records automation errors in `~/Movies/Resolve AE Bridge/ae-launch.log`, and explains the manual fallback. If automation is blocked, open the companion panel and click **Open shot from Resolve**, or use **File → Scripts → Run Script File** to run the generated `Open in After Effects.jsx` in the shot's job folder. Failed handoffs remain pending for retry.

Manual sending no longer requires a render preset. **Render for Resolve** checks/creates the QuickTime template when needed, renders the complete linked duration regardless of the work area, and publishes a movie only after successful completion. Cancelled renders and changed composition timing are rejected. Existing queued renders are restored afterward.

The automated tests use simulated host interfaces. After Effects is absent on the development machine; a real Resolve/AE round trip remains unverified.

## Optional Studio background workflow

Select one ordinary video shot, run **Replace with After Effects Composition**, animate it in AE, and save the `.aep`. A background worker renders the saved composition and selects the result as a new take on the same Resolve clip. The original and previous renders remain available in Resolve's Take Selector.

**This is an experimental implementation, not a verified replacement for Adobe Dynamic Link.** It has automated tests with simulated Resolve/AE interfaces. A real round trip has not been tested here: After Effects was not found, and the installed Resolve Python executable exited abnormally during a connection probe.

## Where the command appears

**Workspace → Scripts → Utility → Replace with After Effects Composition** (some Resolve versions display Utility scripts directly in Scripts).

Resolve's documented scripting and Workflow Integration interfaces do not expose an extension point for adding commands to the native timeline clip right-click menu. This implementation therefore cannot provide that exact menu placement. It uses the selected video clip (Resolve 21.0.4+) or the video clip under the playhead when no video clip is selected.

## Requirements and one-time setup

1. macOS, **DaVinci Resolve Studio 21.1+**, licensed After Effects with its `aerender` executable, and Python 3.9+. This version targets Studio's external scripting; Free is not supported by the background update workflow.
2. Open `Dynamic Bridge.pkg` on macOS or `Dynamic Bridge Setup.exe` on Windows (build both with `packaging/build.sh`; they land in `dist/`; the Windows one needs `brew install makensis`). On macOS you can also open `Install.command` or run `python3 install.py`. In every Resolve edition, including Free and the Mac App Store build, use **Workspace → Scripts → Dynamic Bridge - Send to After Effects**, then **Render for Resolve** in the After Effects panel, then **Dynamic Bridge - Apply AE Render**. The package logs to `~/Library/Logs/Dynamic Bridge Install.log`. Each option copies three Resolve menu scripts, the shared bridge, and **Resolve AE Bridge.jsx** into the detected AE installation's `Scripts` folder. Restart both apps. The AE companion appears under **File → Scripts → Resolve AE Bridge**; normal Cmd+S works without opening that companion panel.
3. If AE is elsewhere, use `python3 install.py --ae-app '/path/to/Adobe After Effects.app'`. Missing AE or a protected Scripts folder is reported as **pending**, not installed. Install AE or grant your user write access to its Scripts folder and rerun. Configuration lives at `~/Library/Application Support/Resolve AE Bridge/config.json`; custom job directories and render-template names are preserved on reinstall, while detected app paths and Python are refreshed.
4. In Resolve's **Preferences → System → General**, set **External scripting → Local**. Keep Resolve open while updates run.
5. In AE, enable **Allow Scripts to Write Files and Access Network** in its scripting preferences. macOS may also request permission for the launcher to control After Effects.
6. At manual render time (or the first Studio background handoff), the AE companion automatically saves a compatible existing QuickTime output preset under **Resolve Bridge ProRes** (or your configured template name). It checks the named template first, then ProRes/High Quality/Lossless candidates, and rejects non-QuickTime formats. The codec remains the candidate preset's codec: the template name alone does not force ProRes. If your AE version or language provides no matching preset, AE explains how to create one. For guaranteed ProRes output, create a template with QuickTime → Apple ProRes 422 HQ, RGB, audio off, and resize/crop disabled under that exact name. For transparency, use ProRes 4444 / RGB + Alpha. The API does not expose reliable codec selection, so the installer does not claim to force it.

## Use

1. Open the target timeline and select one video clip. Run **Replace with After Effects Composition**.
2. AE opens a dedicated `Composition.aep` with the trimmed footage. AE may prompt you to save your currently open project first; cancelling that prompt cancels the handoff.
3. Animate and press **Cmd+S**. Keep the generated project path and composition name, duration, frame rate, and dimensions unchanged.
4. After the save is stable for three seconds, `aerender` renders in a separate process. The finished MOV is imported into Resolve, added as a take, and selected. This also saves the current Resolve project, including other unsaved changes in that project.
5. Further saves produce new renders. A save during a render supersedes that render; the newer saved version is rendered next. The shot stays unchanged until a successful render is available. This is render-on-save, not instant live playback.

The first generated project save also triggers a render. Saving with no content changes may not trigger another render. Use **Resume AE Updates** after restarting your computer, after fixing a failed render, or when a watcher has stopped. Use **Stop AE Updates** to stop all bridge watchers; an already running render finishes, but its output is not applied after a stop request. Workers stop after eight hours without a new save.

## Scope and limitations

- Ordinary local video files, matching source/timeline frame rates, 100% speed, and integer-frame trims. No support for retimes, variable-speed maps, reverse/freeze shots, multicam, compound clips, generators, image sequences, RAW or offline media. Unsupported ranges are rejected where the API exposes enough information to detect them. Use a disposable test timeline before relying on a new media type.
- AE receives **original source pixels**, at native source dimensions. Resolve grading, transforms, effects, transitions, and Fusion work are not transferred or baked into the AE composition. Existing timeline processing remains on the Resolve clip and affects the returned take. Existing timeline audio remains untouched; AE audio is not returned.
- Color-management matching between the apps is manual. Validate color, scaling, alpha, and first/last frames on a short sample before using this in a color-managed project.
- Keep the original project/timeline open for automatic placement. Otherwise the finished render waits. Moving, trimming, slipping, changing speed, or replacing the linked clip pauses updates instead of guessing a new destination. Reopening another take from the bridge is allowed.
- **Save As** to a new `.aep` path does not retarget the link. Continue saving the generated file. AE auto-save backups in other paths are ignored.
- Each shot has a lightweight watcher. A shared lock permits **one background render at a time per jobs directory**, limiting competing AE processes. Watchers check file metadata first and hash changed files in chunks; unchanged projects are not reread every three seconds. Close AE projects normally; workers use their saved copies.
- New renders use unique filenames, avoiding overwriting media currently in use by Resolve. Old renders are deliberately retained because timeline takes reference them. Delete only versions you have removed from your project.
- No native right-click menu integration, live preview, or automatic installation of either host app. The manual Lua workflow includes a Windows installer; background Python rendering is macOS-only.

## Status and troubleshooting

Jobs live in `~/Movies/Resolve AE Bridge/<job-id>/` by default:

- `Composition.aep`: edit this project.
- `job.json`: current status, target identifiers, and latest applied save.
- `bridge.log`: worker errors, including scripting connection failures.
- `render-*.log`: Adobe renderer output; check this if the template, codec, font, effect, or license is missing.
- `render-*.mov`: completed versions; imported into Resolve only after a successful renderer exit and duration/FPS validation.

If nothing updates, check `bridge.log`, confirm Studio's Local scripting setting, and run Resume AE Updates. If `aerender` fails, fix the reason in its log, then Resume to retry. The supplied Resolve 21.1.1 bundled Python probe crashed on this machine, so the installer uses the normal Python interpreter that runs it. Compatibility of that interpreter with Resolve must still be verified in a live Studio session.

To uninstall, run Stop AE Updates, allow any active render to finish, and remove the three installed Resolve menu scripts, AE's `Scripts/Resolve AE Bridge.jsx`, and `~/Library/Application Support/Resolve AE Bridge`. Keep job folders until you no longer need their linked project/render files. `installation.json` in the support folder records the AE script path and any pending setup.

## Development / verification

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile resolve_ae/bridge.py install.py scripts/*.py
node --test tests/test_ae.cjs
```

Before production use, perform a real smoke test: a ten-frame 100% speed shot, an unmistakable AE overlay, save, verify exact first/last source frames and timeline placement, save a second change during render, inspect Take Selector, switch projects before a render completes, and verify Stop prevents placement. Test a non-24 fps shot and a source filename with spaces/quotes as well.

Implementation references: the installed Blackmagic `Developer/Scripting/README.md`, `CHANGELOG.md`, and `Developer/Workflow Integrations/README.txt`; [Adobe automation overview](https://developer.adobe.com/after-effects/); [Adobe automated rendering](https://helpx.adobe.com/th_en/after-effects/desktop/render-and-export/automate-rendering/automated-rendering-network-rendering.html).
# Dynamic-Link
