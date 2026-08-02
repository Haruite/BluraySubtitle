# Refactoring History

[简体中文](refactoring-history.zh-Hans.md)

## Purpose

This document is the durable record of the Python refactor. It records what each completed phase or workflow changed, which behavior changed, what was tested, and what was deliberately deferred.

The detailed Phase 1 analysis remains in [Phase 1 Refactoring Contract and Configuration Matrix](phase-1-contract-and-configuration-matrix.md). All future changes must also follow the mandatory [Code Modification Standards](../development/code-standards.md).

## Maintenance Rule

Every completed refactoring or major change must update this file and its Simplified Chinese counterpart in the same change. Ordinary changes do not require a history entry. Each entry must include:

- scope and commit;
- redundant or conflicting paths removed;
- business-logic changes, including old and new behavior;
- documentation and i18n changes;
- automated checks and remaining manual media checks;
- explicitly deferred work.

History entries must reflect the author's documented intent. Unresolved behavior must be recorded as unresolved rather than given an invented conclusion.

## Status

| Stage | Scope | Status | Commit |
| --- | --- | --- | --- |
| Phase 1 | Contract, configuration matrix, and safety baseline | Complete | `d0262d5` |
| Phase 2 | GUI-to-worker-to-service configuration ownership | Complete | `ceb2927` |
| Phase 3.1 | Merge Subtitles workflow | Complete | `7def4df` |
| Phase 3.2 | Add Chapters workflow | Complete | `107cea1` |
| Phase 3.3 | Blu-ray Remux workflow | Complete | `b89f995` |
| Phase 3.4 | Blu-ray Encode workflow | Complete | `d4adee2` |
| Phase 3.5 | SP, track alignment, and missing-track repair | Complete | `51fbbea` |
| Phase 3.6 | Audio conversion and Dolby Vision | Complete | `3f74ca0` |
| Phase 4 | Shared logic and execution boundaries | Complete | `c50f4e9` |
| Phase 5 | Base contracts, i18n, naming, and algorithm notes | Complete | `b26803b` |
| Phase 6 | Transport and subtitle parsers | Complete | `ef9ea71` |

## Phase 1 — Contract and Safety Baseline

Date: 2026-07-20
Commit: `d0262d5` (`chore: establish phase 1 refactoring baseline`)

### Scope

- Scanned the Python project and documented the existing GUI/configuration/service flow.
- Recorded confirmed product rules and unresolved ownership problems.
- Established regression and static-analysis infrastructure before changing workflows.

### Implementation

- Added the Phase 1 contract and configuration matrix.
- Synchronized the declarations in `gui_base.py` and `service_base.py` with their split mixins for IDE compatibility.
- Added the split-contract checker and the i18n debt ratchet.
- Added source-integrity, configuration-characterization, pure-helper, and static-quality tests.
- Added `run_tests.py` as the concentrated test entry point.
- Established CRLF for newly added non-shell files.

### Logic Changes

No intended product workflow behavior changed. This phase established the rules and characterization boundary needed to identify later behavior changes safely.

The confirmed contracts included:

- current GUI values are authoritative;
- an invalid explicit value must cause an error, not a fallback;
- deterministic output collisions are errors;
- Blu-ray DIY remains visible but incomplete;
- track-language edits must be applied, while generic video conversion is not part of Remux or Encode;
- public facade/API compatibility is not a refactoring requirement.

### Verification

- Python parsing and import smoke tests.
- Configuration and pure-helper characterization tests.
- i18n audit baseline.
- GUI/service split-contract audit.

### Deferred

No production workflow was rewritten. The configuration boundary and each workflow remained scheduled for later phases.

## Phase 2 — Explicit GUI and Runtime Configuration

Date: 2026-07-20
Commit: `ceb2927` (`refactor: unify GUI and runtime task configuration`)

### Scope

Established one explicit configuration path from the current GUI state through workers into Remux/Encode services.

### Redundant or Conflicting Paths Removed

- Removed the legacy global `CONFIGURATION` state and its imports.
- Removed fallback from a failed current GUI configuration to an older snapshot.
- Removed worker-side preassignment of `BluraySubtitle.configuration` when the same configuration was already passed to the service.
- Removed output-name and row-alignment fallbacks that could detach visible GUI rows from runtime values.

### Logic Changes

- The current series configuration is regenerated from current widgets at launch; movie configuration is refreshed before capture.
- Empty or invalid current configuration now stops the task instead of reusing stale state.
- Workers pass the exact configuration object to the service boundary.
- Episode service paths require explicit configuration and reject invalid chapter ranges before writing.
- Every selected main MPLS must correspond to exactly one non-empty Remux command. Missing or extra command lines are launch errors.
- Visible episode output names and row ordering remain aligned with the request.
- Deterministic missing sources and invalid selected rows are reported before execution when practical.

### Documentation and i18n

- Updated both README versions with the WYSIWYG and no-stale-fallback rules.
- Documented the one-main-MPLS-to-one-command rule.
- Added bilingual error messages for configuration and row validation.

### Verification

- Added GUI configuration, command-count, output-name, invalid-range, and service-boundary tests.
- Added explicit RemuxWorker and EncodeWorker configuration-transfer tests.
- Added a source-integrity test proving that legacy global `CONFIGURATION` no longer exists.
- Ran Python compilation/import, i18n, split-contract, and repository tests.

### Deferred

This phase unified ownership but did not yet rewrite the individual Remux, Encode, SP, audio, or Dolby Vision workflows.

## Phase 3.1 — Merge Subtitles Workflow

Date: 2026-07-20
Commit: `7def4df` (`refactor: unify subtitle merge workflow`)

### Scope

Rebuilt Merge Subtitles as an independent request/worker/service workflow for both series and movie mode.

### Redundant or Conflicting Paths Removed

- Removed separate series/movie execution branches that rebuilt overlapping state.
- Removed reuse of stale subtitle checkbox state; selected rows are read from the table at launch.
- Removed hidden configuration preassignment in the worker.
- Removed output writing that could partially proceed before every deterministic collision was known.

### Logic Changes

- One immutable merge request captures the Blu-ray path, selected subtitle files, selected main playlists, suffix, completion option, and movie mappings.
- Series and movie mode use the same service entry point.
- SRT, ASS, SSA, and SUP are supported. Formats cannot be mixed within one merged output.
- The suffix is applied exactly as displayed in the GUI.
- Every planned disc-level and playlist-level output is derived before writing; duplicates or existing files abort the task without overwrite.
- SUP subtitles can be appended and written through the same subtitle-domain interface.
- **Complete Blu-ray Folder** is applied consistently in series and movie mode.

### Documentation and i18n

- Updated both README versions with supported formats, suffix behavior, output locations, and collision behavior.
- Added bilingual validation and output messages.

### Verification

- Added deterministic merge tests for SRT/SUP output, series/movie request capture, mapping errors, mixed formats, suffixes, and existing-output safety.
- Added the merge worker boundary test.
- Ran Python compilation/import, i18n, split-contract, and repository tests.

### Deferred

Merge-only changes did not redesign Add Chapters, Remux, Encode, SP, audio conversion, or Dolby Vision.

## Phase 3.2 — Add Chapters Workflow

Date: 2026-07-20
Commit: `107cea1` (`refactor: unify add chapters workflow`)

### Scope

Rebuilt Add Chapters as an independent GUI request, background worker, and plain-data service path.

### Redundant or Conflicting Paths Removed

- Removed synchronous execution from the GUI thread.
- Removed swallowed GUI configuration errors and fallback to legacy table/configuration behavior.
- Removed Qt table objects from the service boundary.
- Removed dependence on the shared working-directory `chapter.txt`.
- Removed the call to `completion()` that could misinterpret **Edit Original File Directly** as permission to complete the Blu-ray folder.

### Logic Changes

- The request captures the current visible MKV order, selected main playlists, exact source/output pairs, and direct-edit mode once at launch.
- MKVs and selected playlists are matched sequentially by duration and playlist chapter marks. `BD_Vol_NNN` is not required.
- All chapter documents are planned before any MKV is changed. If selected playlists cannot cover every MKV, the task fails before writing.
- Main playlists, MKV inputs, required MKVToolNix executables, duplicate paths, and existing outputs are checked before the worker starts when deterministic.
- Existing outputs are explicit errors.
- Chapter files are per-task temporary files.
- `mkvmerge` and `mkvpropedit` run without shell command-string construction; failure return codes are reported. MKVToolNix return code 1 remains accepted as success with warnings.
- A trivial single zero-time chapter still leaves a direct-edit source unchanged. In new-output mode, an output MKV is still created without adding that trivial chapter.

### Documentation and i18n

- Updated both README versions with ordering, playlist matching, direct-edit/new-output behavior, preflight, and collision rules.
- Added bilingual workflow, tool, mapping, and command-failure messages.
- Synchronized worker exports and GUI/service IDE base contracts.

### Verification

- Added tests for immutable request capture, direct-edit mode, current table order, output collisions, sequential multi-playlist matching without filename markers, pre-write mapping failure, worker/service boundaries, and trivial-chapter output.
- The concentrated repository run completed 49 tests successfully.
- Python compilation, i18n audit, split-contract audit, `git diff --check`, and CRLF checks passed.

### Manual Media Checks Still Required

- New-output mode with real MKVs and MKVToolNix.
- Direct-edit mode on disposable MKV copies.
- Existing-output launch failure.
- Visible table reordering.
- Optional multi-main-MPLS sequential matching.

### Deferred

The legacy chapter entry still used internally by Remux/Encode remains until those workflows are refactored. Their broader orchestration was not changed in this batch.

## Windows Environment Setup Script — Phases 1–5

Date: 2026-07-23

### Summary

- Phase 1 added the elevated, bilingual Windows 10/11 x64 bootstrap, fixed paths, system proxy support, temporary-directory cleanup, and resumable state.
- Phase 2 added the Python and native build toolchain, including conditional MSYS2 setup only when compiled outputs need work.
- Phase 3 added the media inspection, muxing, conversion, and disc utility executables used by the application.
- Phase 4 added x264, multi-bit-depth x265 and SVT-AV1, fdkaac, and libass preparation.
- Phase 5 added the portable VapourSynth Classic environment with embedded Python 3.13, NumPy, VSEdit, scripts, and the 15 baseline plugins.
- All phases detect existing installations, skip satisfied components, and repair or upgrade components when required.

### Verification

- The single Windows setup test module contains 49 passing tests.
- PowerShell parsing, file-format, and whitespace checks passed.
- A complete clean-machine installation remains a manual verification.

## Phase 3.3 — Blu-ray Remux Workflow

Date: 2026-07-22
Commit: `b89f995` (`refactor(remux): rebuild main playlist workflow`)

### Scope

Rebuilt the Remux GUI request, worker boundary, preflight plan, main-playlist execution, and final output mapping. The existing fallback algorithms remain available, but now execute within one deterministic job per selected main playlist.

### Redundant or Conflicting Paths Removed

- Removed the worker's long list of mirrored GUI arguments and repeated service configuration assignments.
- Removed per-disc grouping that could execute only the first main playlist when several selected main playlists belonged to the same disc.
- Removed early output-directory creation and later directory scanning used to rediscover task outputs.
- Removed automatic output-name character replacement, numeric collision suffixes, and fallback to unrelated raw output files.
- Removed the forced **Complete Blu-ray Folder** state.

### Logic Changes

- One owned Remux request captures the current GUI configuration, selected main playlists, visible output names and languages, SP rows, track settings, default audio codec, movie mode, trimming, Dolby Vision, and folder-completion option.
- Selected main playlists are planned in visible order. Each selected main playlist must produce exactly one non-empty command and one execution job, including multiple main playlists from the same disc.
- The GUI command preview consumes the same seven-value command result as execution. If command generation fails, the preview remains empty and is rejected during configuration capture instead of synthesizing an executable-looking command without the planned output path or track options.
- Every theoretical command output and final GUI output path is derived before the output directory is created. Configuration-row counts, chapter ranges, duplicate paths, and existing files are validated before writing.
- Final names are applied exactly as displayed. A missing `.mkv` extension is appended; invalid Windows file names are explicit errors.
- A main command or fallback must produce every planned output for its job. Missing outputs now fail the task instead of being silently skipped; task-created partial expected outputs are removed after failure.
- Finalization consumes the planned output list rather than scanning the destination directory, and uses a task-local temporary chapter file.
- Chapter metadata is edited in the newly generated task outputs regardless of the folder-completion checkbox; that checkbox controls only Blu-ray folder completion.
- Languages saved by **Edit Tracks** are captured per main-playlist job, and `mkvpropedit` availability is checked before output creation. After either the primary command or any fallback succeeds, only the configured languages for included tracks are applied; the output is identified again and verified. Mapping, command, or verification failure fails the job and removes its newly created main outputs.
- Episode output order remains aligned with configuration order for later subtitle, language, SP, audio, and Dolby Vision processing.
- **Complete Blu-ray Folder** now follows the captured checkbox value exactly.

### Documentation and i18n

- Updated both README versions with the one-main-playlist-to-one-job rule, pre-write output planning, exact naming, collision behavior, strict completion, checkbox ownership, and verified main-output language correction.
- Added bilingual validation, command-failure, missing-output, output-mapping, and language-correction messages.
- Updated the service IDE compatibility declarations and the repository batch-movie caller.

### Verification

- Added tests for GUI request capture, complete command preview, failed-preview rejection, same-disc multiple main playlists, one-command jobs, duplicate and existing outputs, invalid chapter ranges before directory creation, failed commands, exact final naming, temporary chapter cleanup, language capture, preflight tool availability, fallback language correction, and verified `mkvpropedit` arguments.
- Updated worker-boundary and configuration-characterization tests for the explicit request contract.
- The concentrated repository run completed 58 tests successfully.
- Python compilation, i18n audit, split-contract audit, `git diff --check`, and CRLF checks passed.

### Manual Media Checks Still Required

- Series Remux from `E:\BDMV`, including visible episode names, chapter ranges, subtitle languages, and track settings. Change at least one selected audio or subtitle language in **Edit Tracks**, then inspect the final MKV metadata.
- Movie Remux of the available Avatar and both Zootopia discs, especially their remux-fallback paths.
- Existing-output collision without any new output, and optional same-disc multiple-main-playlist order.
- **Complete Blu-ray Folder** both disabled and enabled; enabled tests must use a disposable source copy because completion changes the Blu-ray folder.

### Deferred

SP, including its own output-language mapping, track alignment and missing-track repair, audio conversion, and Dolby Vision internals were not redesigned in this workflow. Encode only adopts the shared main-Remux planning boundary needed to keep that code path working; its broader orchestration remains for Phase 3.4.

## Phase 3.4 — Blu-ray Encode Main Workflow

Date: 2026-07-22
Commit: `d4adee2` (`refactor(encode): unify Blu-ray and Remux encode workflows`)

### Scope

Rebuilt the Encode launch, worker, Blu-ray staging, and shared row-execution path for both Blu-ray and Remux inputs. SP mux algorithms, track alignment, missing-track repair, audio conversion algorithms, and Dolby Vision algorithms remain in their later workflow phases.

### Redundant or Conflicting Paths Removed

- Removed the duplicated Blu-ray/Remux GUI launch branches and their duplicated thread cleanup and signal wiring.
- Removed the worker's long mirrored parameter list in favor of one immutable Encode request.
- Removed `EncodeMkvFolderWorker` and the nested synchronous Worker call inside the service. Execution failures now propagate to the one GUI Worker instead of being converted into an inner signal and then followed by a false outer success.
- Removed parallel arrays for subtitles, output names, languages, VPy paths, configurations, and SP entries. Each visible row now owns its related values and exact output path.
- Removed directory scanning used to rediscover staged main outputs after Remux.
- Removed Encode's hidden **Complete Blu-ray Folder** read, forced enabled state, and `completion()` call.
- Removed legacy silent existing-output skips, best-effort copy failures, and runtime regeneration of a missing explicit VPy file. Remux-source resume now follows one explicit documented rule instead.

### Logic Changes

- One request captures the input mode, ordered main/SP rows, exact outputs, subtitles and languages, VPy paths, all encoder controls, trimming and Dolby Vision controls, and track settings before the worker starts.
- Both input modes use one Worker and one shared row executor. Source-specific code now only decides whether source MKVs already exist or must first be Remuxed into staging.
- Deterministic preflight checks the source, selected main playlists, row/configuration counts, VPy files, required tools, output containment and names, duplicate paths, strict Blu-ray output collisions, and a non-empty staging directory before worker launch.
- Blu-ray input uses the exact Remux main-job planner and finalizer. Planned names, chapters, fallback behavior, selected tracks, and track-language corrections are retained in the staged sources before encoding.
- Encode never completes or mutates the selected Blu-ray source. It owns only its disc subfolder under `_encode_remux_stage`; cleanup does not remove a pre-existing staging parent.
- Remux input keeps non-MKV companion files at their relative paths. External subtitle filenames follow each visible main output basename in both input modes. Duplicate destinations within one request and copy failures are errors.
- Blu-ray input rejects existing planned outputs. Remux input treats existing planned main/SP outputs, external subtitles, and companion files as completed, reports each skip, and continues with the remaining rows without overwriting anything.
- Missing row outputs after `encode_task` are errors. A nonzero encoder pipeline, missing encoded elementary stream, failed VPy source update, failed Dolby Vision preparation/injection, or failed final `mkvmerge` now stops the task. Video encode failure cannot continue into audio processing and accidentally mux the original video.
- Episode-linked SP rows remain represented in the request but are not encoded twice after their staged effect has already been applied to the main source.

### Documentation and i18n

- Updated both README versions with the single-request contract, preflight, exact outputs, staging ownership, companion/external-subtitle behavior, and strict pipeline failure behavior.
- Added bilingual Encode preflight, progress, missing-output, tool, VPy, and pipeline-failure messages.
- Synchronized service IDE declarations and removed the obsolete worker exports.

### Verification

- Added focused tests for GUI request capture without the hidden checkbox, duplicate outputs, strict Blu-ray collisions, resumable Remux outputs and sidecars, output containment, missing VPy files, shared executor failure behavior, Blu-ray staging ownership, and encoder-failure propagation before audio/mux.
- Updated the worker boundary test for the immutable request.
- The concentrated repository run completed 114 tests successfully.
- Python compilation, i18n audit, split-contract audit, `git diff --check`, and CRLF checks passed.

### Manual Media Checks Still Required

- Encode one short anime episode from `E:\BDMV` and verify the visible output name, chapters, selected tracks, edited track languages, chosen VPy, encoder, bit depth, parameters, subtitle mode, and lossless-audio choice.
- Encode a short test from a Remux folder and verify the same settings plus external-subtitle naming and relative companion-file copies.
- Confirm Blu-ray input rejects an existing main/SP output before writing any new final output.
- Start a Remux-source task with some existing main/SP/subtitle/companion outputs and some missing outputs; confirm existing files remain unchanged, each skip is reported, and the remaining outputs are produced.
- Force an encoder failure with a disposable short task and confirm that no final MKV is reported as successful.
- Exercise a Dolby Vision source with supported settings and an intentionally unsupported setting. Use disposable output/staging directories; the source Blu-ray directory should remain unchanged.

### Deferred

SP muxing and special-output algorithms, track alignment and missing-track repair, lossless-audio conversion internals, and Dolby Vision preparation/injection internals were not redesigned. This phase changes only their request/orchestration boundary and failure propagation where required to make the Encode main workflow truthful.

## Phase 3.5 — SP, Track Alignment, and Missing-Track Repair

Date: 2026-07-24
Commit: `51fbbea` (`refactor(sp): rebuild SP and track-alignment workflow`)

### Scope

Rebuilt SP request capture, preflight planning, mux/extract execution, episode-linked SP handling, track-aligned fallback, and missing-track repair. Remux and Blu-ray-source Encode now use the same SP planner and executor.

### Redundant or Conflicting Paths Removed

- Removed the legacy SP executor that rediscovered sources and outputs at runtime, swallowed command failures, and continued after selected rows failed.
- Removed the old directory-rescan SP branch and the separate single-clip and multi-clip aligned fallback implementations.
- Removed unused duplicate silence-patching and slot-planning helpers.
- Removed the track-editor side effect that copied an SP row's audio/subtitle selection into the main-playlist configuration.
- Replaced best-effort shell execution in the SP primary, raw extraction, image extraction, episode-linked mux, chapter restore, silence generation, and aligned concatenation paths with checked argument-list execution.

### Logic Changes

- Each visible SP row is captured as an immutable entry. Remux and Blu-ray-source Encode refuse to launch while the SP track scan is still running.
- All selected non-empty SP rows are planned before the task creates its first output directory. Planning resolves the exact source, exact visible output, selected tracks, edited languages, duplicate/existing outputs, and episode-output links.
- Unchecked rows and rows whose empty output name intentionally represents no selected track remain skipped. Any other selected SP failure now stops the task instead of being silently ignored.
- Container muxing explicitly disables unselected audio/subtitle tracks, and `.mka`/`.mks` outputs explicitly disable video. The exact GUI output name is used without runtime renaming or output rediscovery.
- SP track languages are applied and verified on standalone container outputs. Episode-linked SP languages are applied only to newly appended SP tracks; the original episode is atomically replaced only after mux, chapter restoration, and language verification succeed. Raw/image outputs reject language metadata before execution.
- One shared aligned fallback now handles both one-clip and multi-clip playlists. It maps each clip to the reference PID layout, requires tsMuxer to recover missing non-audio tracks, tries tsMuxer for missing audio, fills only the remaining audio gaps with format-matched silence, and verifies the final PID set before using the result.
- `mkvmerge` return code 1 is consistently accepted as success with warnings in the aligned fallback, while a missing planned output still fails the task.

### Documentation and i18n

- Updated both README versions with exact SP request behavior, failure handling, language support, unified alignment, and the tsMuxer-before-silence repair order.
- Added bilingual SP scan, preflight, execution, language, source, output, chapter, and fallback messages.
- Synchronized the service IDE compatibility declarations and updated the batch Remux caller for the typed SP contract.

### Verification

- Added focused tests for exact SP outputs/tracks/languages, missing captured configuration, existing outputs, episode links, explicit track disabling, selected-row failure, shared single-clip fallback, tsMuxer-unavailable audio silence, and unrecoverable non-audio tracks.
- The concentrated repository run completed 125 tests successfully.
- Python compilation/import, i18n audit, split-contract audit, and `git diff --check` passed before the final line-ending audit.

### Manual Media Checks Still Required

- Remux an anime disc from `E:\BDMV` with several selected and unselected SP rows; verify visible output names, raw/container/image types, chapters, track selection, and existing-output rejection.
- Edit one SP audio or subtitle language and verify the final `.mkv`, `.mka`, or `.mks` metadata. Also test an episode-linked SP row and confirm the episode chapters and original tracks remain intact.
- Exercise both a one-clip and a multi-clip track-aligned fallback. Confirm missing audio is recovered by tsMuxer when available and uses silence only when recovery is unavailable; an unrecoverable missing subtitle/video track must fail.
- Repeat the selected SP checks through Blu-ray-source Encode staging. The original Blu-ray directory must remain unchanged.

### Deferred

Audio-conversion algorithms and Dolby Vision preparation/injection remain Phase 3.6. This phase only preserves their existing integration points while refactoring SP and track alignment.

## Phase 3.6 — Audio Conversion and Dolby Vision

Date: 2026-07-24
Commit: `3f74ca0` (`refactor: simplify audio conversion and Dolby Vision handling`)

### Scope

Rebuilt the Encode audio-conversion and Dolby Vision paths around the immutable per-row request. Removed hidden Remux audio conversion, unified Dolby Vision command execution, and made non-fallback conversion or Dolby Vision preservation failures stop the task.

### Redundant or Conflicting Paths Removed

- Removed post-Remux audio conversion and the hidden dependency on Encode's default/per-track audio settings. Remux now preserves the selected source audio exactly.
- Removed the legacy audio path that rescanned output folders, used fuzzy global track maps, extracted container tracks into guessed elementary-stream names, and silently removed or substituted tracks after conversion failures.
- Removed duplicate FLAC/extraction/conversion entry points, temporary `info.json` state, output-size fallback decisions, and silent/duplicate-audio cleanup heuristics.
- Removed the duplicated Encode Dolby Vision helpers, shared work folder, shell command construction, and separate BL/EL mux implementation. Encode injection and Remux BL/EL mux now use one checked module.

### Logic Changes

- Each visible Encode row captures its selected audio/subtitle track IDs, effective FLAC/AAC/Opus choice for every selected audio track, and edited track languages before the Worker starts.
- Only PCM, TrueHD/MLP, DTS-family, and FLAC tracks are conversion candidates. Lossy audio remains unchanged, and FLAC selected as FLAC is not recompressed.
- Remux-source preflight identifies the selected audio before launch and checks only tools required by actual conversions. Existing checkpoint outputs, lossy audio, and FLAC-to-FLAC selections do not add unnecessary tool requirements.
- Selected audio tracks retain their source order and their language, name, default/forced flags, and delay metadata. Except for the documented TrueHD Atmos preservation fallback, a selected conversion, extraction, final mux, or verification failure stops the row; the final output is replaced atomically only after verification succeeds.
- TrueHD Atmos is converted only after `truehdd` successfully decodes presentation 2. If `truehdd` is unavailable or its decode fails, that track skips conversion and the original TrueHD stream is retained. Standalone `.mka` SP outputs stay as `.mka` containers.
- Blu-ray-source Encode applies languages during its owned staging Remux and does not reinterpret the original Blu-ray track IDs during the final mux. Episode-linked SP audio choices follow the appended staged-track order.
- Remux's **Mux Dolby Vision** option continues to control whether compatible base and enhancement layers are combined as profile 8.1. Disabled means the enhancement layer is excluded.
- Encode Dolby Vision preservation uses mode 2 RPU conversion in a unique task-owned work folder and injects only into an x265 10-bit or 12-bit HEVC stream. SVT-AV1 accepts Dolby Vision sources but emits an explicit task message and omits Dolby Vision metadata because the current toolchain cannot author AV1 Dolby Vision profile 10. x264 and x265 8-bit preservation requests are rejected. Output replacement and cleanup are task-scoped.

### Documentation and i18n

- Updated both README versions with the Remux/Encode audio boundary, the TrueHD Atmos preservation fallback, explicit failures, and the current x265/SVT-AV1 Dolby Vision behavior.
- Added bilingual audio extraction, conversion, TrueHD Atmos preservation, mux verification, Dolby Vision preparation/injection, SVT-AV1 metadata-omission, cleanup, and unsupported-setting messages.
- Synchronized the service IDE compatibility declarations with the reduced implementation surface.

### Verification

- Added focused tests for preserving lossy audio, successful lossless replacement with metadata, TrueHD Atmos preservation when `truehdd` is unavailable or fails, exact track/language muxing, explicit conversion failure and cleanup, x265 Dolby Vision preservation restrictions, SVT-AV1 processing without Dolby Vision injection, mode 2 RPU preparation, atomic BL/EL replacement, and unique task work folders.
- Updated Encode/Remux request-capture and helper characterization tests for the new per-row contract and removed hidden Remux audio settings.
- The concentrated repository run completed 139 tests successfully.
- Python compilation, i18n audit, split-contract audit, `git diff --check`, and CRLF checks passed.

### Manual Media Checks Still Required

- Encode a short anime title from `E:\BDMV` with multiple selected audio tracks and choose different FLAC/AAC/Opus targets. Verify audio order, codecs, languages, names, default/forced flags, delays, and that an existing lossy track remains unchanged.
- Repeat with a standalone `.mka` SP and an episode-linked SP; verify the output remains a valid container and appended-track choices match the GUI order.
- Change Encode audio choices, then run Blu-ray Remux for the same selection and confirm Remux audio is unchanged.
- Test Dolby Vision Remux with **Mux Dolby Vision** enabled and disabled, then Encode the Dolby Vision title with x265 10/12 bit and SVT-AV1. Confirm x265 retains profile 8.1, SVT-AV1 explicitly reports that Dolby Vision metadata is omitted, and x264/x265 8-bit preservation requests are rejected. Inspect every result with MediaInfo.
- Repeat the relevant checks on a disc that enters `remux-fallback`, including `E:\Movies\疯狂动物城2.Zootopia 2 2025 2160p UHD Blu-ray DoVi HDR10 HEVC TrueHD 7.1-x-man@HDSky`.

### Deferred

AV1 Dolby Vision profile 10 authoring remains deferred until the project has a verified compatible encoder and packaging path. Video transcoding from **Edit Tracks** and the unfinished Blu-ray DIY encode path also remain outside this phase.
## Phase 4 — Shared Logic and Execution Boundaries

Date: 2026-07-24 to 2026-07-25
Commit: `c50f4e9` (`refactor: consolidate shared logic and execution boundaries`)

### Scope

Simplified cross-workflow Python infrastructure after the workflow refactors. This phase consolidated configuration generation, displayed-time and M2TS-detail parsing, output-title resolution, track keys, binary integer reads, and external process execution without introducing a new product workflow.

### Redundant or Conflicting Paths Removed

- Removed the legacy table-based episode-configuration algorithm. GUI callers now adapt current selections to the single selected-MPLS generator instead of maintaining a second algorithm.
- Moved displayed-time parsing and SP M2TS-detail parsing, containment, and filtering to shared helpers; removed the duplicate GUI and service copies.
- Replaced repeated `main::`, `mkv::`, `mkvsp::`, and SP track-key construction with the shared track contracts.
- Consolidated the three duplicated subtitle-change configuration refresh blocks into one GUI operation and simplified the GUI output-title adapter to the existing service owner.
- Removed silent fallback from current GUI configuration generation to a separately regenerated default configuration.
- Removed disabled UI-performance, SP-diagnostic, and chapter-trace facades and their diagnostic-only variables.
- Removed duplicate Encode logging and shell-command wrappers, obsolete split-base declarations, unused imports, and assignments overwritten before their first use.
- Routed all subprocess-based external-tool launches through `run_command`; command lists run without a shell and command strings use the shell at this single boundary. VSEdit remains a Qt-owned `QProcess` because its completion signals synchronize temporary scripts, while OS file-association opens are not tool commands.
- Inlined one-use expression wrappers for playlist loop keys/durations, process flags, chapter timecodes, cache keys, output sanitizing, M2TS cache signatures, encoder arguments, and Remux-fallback PID/FPS/file-type/channel decisions; removed their matching split-base declarations.
- Replaced the branch-heavy Matroska codec-name and extraction-extension selectors with one `_MKV_CODEC_INFO` lookup table.
- Removed the unused `src/domain/subtitle.py` and `src/exports/subtitle_models.py` compatibility facades and the singular `M2TS.get_track_info()` compatibility wrapper.
- Removed a redundant relative seek in MKV duration parsing and file-size arithmetic whose result was always the same 512-KiB M2TS probe window.
- Removed the private `Chapter._unpack_byte()` and `M2TS.unpack_bytes()` implementations. Chapter/MPLS/CLPI integer decoding now uses `bdmv.core.unpack_bytes`, while M2TS reads each PCR header block once and sends its multi-byte value through the same decoder.

### Logic Changes

- The conflicting episode-tail tolerance is now consistently 300 seconds. The removed table algorithm already used 300 seconds, the selected-MPLS algorithm used 180 seconds, and both README versions document 300 seconds.
- A failure while rebuilding configuration from current GUI controls is no longer replaced by a newly generated default configuration. The original error reaches the existing GUI error boundary or task preflight.
- External process start and execution failures now follow the caller's existing checked return-code or exception path instead of the removed best-effort shell wrapper returning a synthetic `-1`.
- The incomplete GUI-local ffprobe wrapper started the tool but returned no stream list. Non-M2TS SP output-extension detection now reuses the complete service media probe instead of receiving `None`.
- Encode services now consume the canonical encoder and bit-depth values accepted by `validate_encode_request`. Unknown encoder labels are no longer converted to x265 and invalid bit depths are no longer converted to 10-bit after preflight; invalid configuration fails at the request boundary.
- Binary parser results, output-title rules, valid track selections, valid Remux/Encode/SP behavior, audio conversion, and Dolby Vision product behavior are otherwise unchanged.

### Documentation and i18n

- No README product change was required because the retained 300-second rule already matches both README versions.
- No new user-visible string was introduced; the i18n debt ratchet remains unchanged.
- Synchronized this history entry in English and Simplified Chinese.

### Verification

- Source Python lines decreased from 35,671 to 34,420; function definitions decreased from 1,419 to 1,308.
- Non-stub functions of six lines or fewer decreased from 213 to 177. A repository-wide one-use helper audit retained short functions only when they are callbacks, serialization/process-pool entry points, data-model methods, or independently meaningful parser/domain operations.
- A repository-wide AST audit found no duplicate function definitions in modified modules; the remaining short-function list was reviewed by role instead of line count alone.
- Before and after the binary-reader consolidation, structured snapshots from `00000.m2ts`, `00003.mpls`, and `00003.clpi` on the specified Cyberpunk: Edgerunners disc were identical in every field. The comparison covered PCR/PTS values, durations, frame rate, total frames, tracks, content type, complete MPLS/CLPI parse trees, chapters, PID languages, and byte-identical MPLS serialization.
- The concentrated repository run completed 138 tests successfully; the test for a deleted argument-splitting helper was replaced by an Encode workflow assertion on the resulting encoder command.
- Python compilation/import, i18n audit, split-contract audit, `git diff --check`, and CRLF checks passed.

### Manual Media Checks Still Required

- Change subtitle selection/order and chapter bounds in the GUI, then verify the visible Remux/Encode rows remain the configuration used at launch and that an invalid current value reports an error without a default fallback.
- Run one short Remux and one short Encode task to cover the unified Windows command boundary, then inspect final names, tracks, languages, and chapters.
- Use an SP-bearing disc to verify the shared M2TS-detail containment/filtering keeps the existing selected/unselected behavior and output names.

### Deferred

The remaining very long functions represent existing independent GUI construction or workflow stages and were not split merely to reduce their measured length. Blu-ray DIY encoding and generic video conversion in Edit Tracks remain outside this phase.

## Phase 5 — Base Contracts, i18n, Naming, and Algorithm Notes

Date: 2026-07-25
Commit: `b26803b` (`refactor: complete phase 5 contracts and workflow cleanup`)

### Scope

Made the GUI/service split contracts reproducible, completed the remaining source-language cleanup, replaced unclear fallback and timeline names, documented the algorithms most likely to need future maintenance, and removed a file that existed only to hold an empty cancellation sentinel.

### Structural Changes

- `tools/check_split_contracts.py` now generates and verifies the marked method-declaration sections in both `gui_base.py` and `service_base.py`. `--write` updates both bases from their mixins; the normal check fails when either generated section is stale, and repeated generation is byte-stable.
- Replaced the private `_Cancelled` class and its dedicated `services/cancelled.py` module with the shared `runtime.TaskCancelled` exception. GUI workers and service mixins now use the same cancellation type.
- Removed hard-coded Simplified Chinese from source modules. GUI headers, language names, task labels, hints, and other translated strings now start from English source text and resolve through `I18N_ZH_TO_EN`.
- Replaced abbreviated fallback, chapter-window, track-map, input-path, and Dolby Vision variables with names that describe their role. Removed unused values and one-use formatting/parsing wrappers encountered during the same edits.
- Added English comments for chapter half-open ranges, split-timeline projection, first-play-item PID slots, Matroska input-local TIDs, episode-linked SP mapping, missing-track repair, PCM silence generation, and Dolby Vision profile conversion.

### Logic Changes

- Track-aligned Remux fallback now uses only tracks visible and selected in Edit Tracks. First-M2TS streams hidden by the MPLS are excluded, selected video indexes are mapped to each later clip, and recovered tracks or silence keep the GUI selection order instead of numeric PID order.
- A video-only dual-layer Dolby Vision SP retains the base-layer PID as one logical output slot when **Mux Dolby Vision** is enabled. The raw BL/EL tracks remain excluded from the direct Matroska input, and the combined video can be muxed without an audio/subtitle base MKV.
- Each multi-clip fallback part removes its own `*_tsmux_out` and `*_audrec_tsmux_out` directory immediately after that part succeeds or fails; final part MKVs remain available for concatenation.
- Every repair merge rebuilds the current PID-to-Matroska-TID map before a later repair stage. This prevents a track reorder caused by one merge from leaving stale TIDs for the next merge.
- Missing non-audio tracks remain an all-or-nothing tsMuxer repair. Missing audio first uses tsMuxer and falls back to PCM silence only when demux is unavailable; the silence inherits sample rate, channel count, and bit depth from the reference slot. The obsolete source-codec whitelist was removed because the generated replacement is PCM regardless of the missing codec name.
- Fallback now accepts only the exact planned part output. It no longer searches for an arbitrary same-prefix intermediate MKV and promotes that file as a successful result.
- Chapter-bound lookup now uses `bisect_left` for the existing monotonic one-millisecond-tolerant boundary rule. The resulting half-open chapter ranges and rebased timestamps are unchanged.
- Episode-linked SP accepts only a valid `stream_id` or `original_transport_stream_id` as the transport PID. A selected SP track without either value fails explicitly; `properties.number` is no longer interpreted as a PID.
- Blu-ray Remux now captures a default-enabled **Convert lossless audio to FLAC** option. After main chapters and all SP muxing are complete, every final Matroska output converts selected lossless audio to FLAC in place through the shared verified audio pipeline; lossy audio and existing FLAC remain unchanged, and disabling the option preserves source audio. AAC and Opus remain Encode-only choices.
- Blu-ray Encode explicitly disables Remux FLAC conversion in its staging request. Its staged source audio remains untouched until video encoding succeeds and the Encode final mux performs the configured per-track audio conversion.
- The shared FLAC target now uses the configured standalone `flac` encoder at compression level 8 with an explicit thread count. TrueHD/DTS-family inputs are decoded to PCM first when necessary; an unavailable or failed standalone encode falls back to `ffmpeg` at compression level 8, and partial FLAC output is removed before fallback. FFmpeg output for actual audio decoding and encoding remains visible.

### Documentation and i18n

- Updated both README versions to state precisely that fallback follows GUI-visible selected track order, excludes MPLS-hidden tracks, gives missing-audio PCM silence the reference sample rate, channel count, and bit depth, and requires real identify PID fields for episode-linked SP.
- Added the remaining GUI table headers and language label to `I18N_ZH_TO_EN`, corrected reversed source/translation entries, and regenerated the i18n debt baseline.
- Added bilingual Remux FLAC option, unavailable-state, and progress text; synchronized the current Remux/Encode audio boundary, compression level, visible FFmpeg output, and standalone FLAC priority/fallback rule in both README and code-standard versions.
- Synchronized this Phase 5 entry in English and Simplified Chinese.

### Verification

- The complete repository run passed all 155 tests, including regression coverage for GUI-visible selected PID order, MPLS-hidden track exclusion, per-clip selected-video mapping, video-only Dolby Vision SP fallback, per-part tsMuxer cleanup, default/disabled Remux FLAC conversion, standalone FLAC priority, level-8 visible ffmpeg fallback in both shared and SP paths, Encode staging audio preservation, explicit SP PID failure, and rejection of same-prefix fallback intermediates.
- Python compilation and source-import checks passed.
- A read-only check of `01478.mpls` / `00304.m2ts` on the Zootopia 2 disc identified only HEVC PIDs `0x1011` and `0x1015`; the corrected plan retained `0x1011` as video index `0` for the combined output.
- Real-tool one-second Matroska checks invoked `flac -8 -j 20` on the preferred path, then forced standalone failure and verified the fallback command used visible FFmpeg output with `-compression_level 8`. PCM converted to FLAC, AC-3 remained unchanged in the preferred-path check, order/language and final codec IDs were verified, and task-owned temporary files were removed.
- The i18n audit reports zero Chinese source comments, zero Chinese source strings outside `core/i18n.py`, and zero unmapped translation calls.
- Split-contract verification passes, and two consecutive `--write` runs produce identical base files.
- `git diff --check`, duplicate-definition/short-file review, and CRLF checks passed.

### Manual Media Checks Still Required

- Run track-aligned fallback on the known meat-paste/remux-fallback discs. Inspect track order, languages, missing-track recovery, chapters, and final duration with MediaInfo and mkvmerge identification.
- Use a case with an audio PID absent from the direct Matroska read. Confirm tsMuxer recovery is preferred and PCM silence is produced only when recovery fails.
- Test a multi-clip title whose fallback needs more than one repair stage, especially one whose first M2TS contains tracks hidden by the MPLS; ensure video, audio, and subtitle selections still match the GUI after each merge.
- Test episode-linked SP on a title whose mkvmerge identify data omits both accepted PID fields; verify the selected row fails with the affected track and source path instead of using `properties.number`.
- Review Simplified Chinese and English GUI table headers, language labels, task hints, and cancellation behavior.
- Exercise Remux and Encode Dolby Vision paths and inspect the resulting profile and track set.
- Run Blu-ray Remux with the FLAC option enabled and disabled on PCM, DTS-HD, TrueHD Atmos, existing FLAC, and lossy audio. Inspect codecs, track order, language/flags, chapters, attachments, and the `truehdd` preservation fallback.
- Run a short Blu-ray Encode and confirm its staging MKV retains source audio while the final output applies the per-track Encode choice only after video succeeds.

### Deferred

Blu-ray DIY encoding and generic video conversion in Edit Tracks remain outside this phase.

## Phase 6 — Transport and Subtitle Parsers

Date: 2026-07-25
Commit: `ef9ea71` (`refactor: complete phase 6 transport and subtitle parsers`)

### Scope

Refactored the M2TS transport parser, the shared media-information bridge, and the ASS-to-PGS converter. The work keeps parser behavior at explicit format boundaries, follows tsMuxer for permissive Blu-ray transport interpretation, and completes the Spp2Pgs-derived PGS timing and buffer rules used by this project.

### M2TS and Media Mapping

- Replaced per-packet file reads with one aligned transport-packet iterator that scans 4 MiB blocks and supports 192-byte M2TS and 188-byte MPEG-TS input. PTS scans, PAT/PMT assembly, frame-rate discovery, PCR duration, and IGS extraction now share this iterator.
- Kept PAT/PMT parsing permissive like tsMuxer: sections are assembled without requiring a valid CRC, multi-packet PMTs remain supported, and the first complete program map ends the normal track probe.
- Removed the PES-PTS frame-rate estimator. A HEVC VPS or AVC SPS now supplies the native timing fields using the same bit order and AVC/HEVC clock distinction as tsMuxer; unsupported native video codecs use the existing explicit ffprobe fallback only when a frame count is requested.
- Replaced the stateful PCR seek/read helpers with direct adaptation-field parsing. Clip duration uses the PCR clock used by tsMuxer and falls back to PTS only when PCR is unavailable; total frames use that duration and the unrounded native rate.
- Removed duplicate IGS PID discovery and reused the normal track parser. A caller-provided skipped-PID set is no longer mutated.
- Replaced three service-level result caches plus the PTS cache with one unchanged-file parser cache. Track, duration, frame-count, and PTS callers now share the same `M2TS` instance and its internal values; the file-size/mtime signature replaces it when the source changes.

### ASS to PGS

- The converter now uses the configured shared `LIBASS_PATH`; direct script execution exposes the repository root before loading the same setting. The selected job count applies to both rendering and PGS payload preparation.
- Corrected libass change handling so every unchanged frame extends the active subtitle segment. Segment ends are consistently exclusive, and identical pixels at different crop coordinates are no longer merged as one stationary subtitle.
- Added rational BDN frame-rate parsing and all eight Blu-ray frame-rate identifiers, including distinct 30 and 60 fps values. Unsupported rates fail instead of being silently mapped to the nearest identifier.
- Ported the Spp2Pgs integer BT.601/BT.709/BT.2020 color matrices, decode-duration formulas, minimum PTS intervals, initial transparent anchor, epoch-gap calculation, and ODS fragmentation sizes.
- Every ODS fragment now receives the selected object version. Because libass has already flattened simultaneous layers into one non-overlapping bitmap event, each clear composition releases the single palette/object slot; the next event redefines slot zero with an incremented palette and object version instead of imposing artificial 8-palette/64-object epoch limits.
- Invalid, overlapping, or decode-incompatible event timing now fails explicitly. The old compatibility path no longer shifts events or drops them silently.
- Removed duplicate packet builders, timecode converters, palette paths, one-use wrappers, redundant image dimensions, and the filename-based compatibility entry point. User-visible command-line text is English in source and has Simplified Chinese entries in `I18N_ZH_TO_EN`.

### Logic Changes

- HEVC and AVC frame counts are now derived from stream timing and tsMuxer-compatible PCR duration. This corrects the previous result that treated multi-access-unit HEVC PES timestamps as frame intervals and could report 6.85 or 11.987 fps with substantially too few frames.
- ASS animation and movement now retain their full unchanged duration and screen position. PGS output uses exact 30/60 fps identifiers, consistent fragment versions, and explicit timing errors rather than modified subtitle timing.
- Valid PAT/PMT track results, M2TS type classification, IGS extraction intent, ASS styling, output resolution, and public Remux/Encode/SP behavior are otherwise unchanged.

### Documentation and i18n

- No README change was required because this phase changes parser correctness and performance rather than a user workflow or option.
- Added bilingual ASS/BDN/PGS command-line descriptions, status messages, and parser errors to `I18N_ZH_TO_EN`.
- Synchronized this Phase 6 entry in English and Simplified Chinese.

### Verification

- Added focused synthetic M2TS/MPEG-TS tests for PAT/PMT tracks, PTS/PCR duration, HEVC VPS timing, total frames, packet-layout detection, and caller-owned PID-set preservation.
- Added ASS-to-PGS tests for all Blu-ray frame-rate identifiers, rational BDN rates, position-sensitive segment merging, full ODS fragment versioning, palette versioning, packet boundaries, and 30 fps PCS output.
- On the largest clips from the three specified movie discs, parsed PID/codec order and 23.976 timing matched tsMuxer. PCR durations matched tsMuxer at 1,888.704, 911.223, and 768.824 seconds; resulting frame counts are 45,284, 21,848, and 18,433. Track scans complete in about 0.003–0.006 seconds and native HEVC timing in about 0.014–0.029 seconds, compared with about 0.13 and 3.1 seconds respectively before this phase.
- The Cyberpunk: Edgerunners `00000.m2ts` AVC check matched tsMuxer for all nine tracks, 23.976 timing, and 1,440.720-second duration; the combined parser query completed in about 0.083 seconds.
- Converted the specified SPY×FAMILY episode 1 ASS into 522 PGS events. ffprobe identified a 1920×1080 `hdmv_pgs_subtitle` stream, and mkvmerge accepted and muxed the 19,956,542-byte SUP without warnings.
- The complete repository run passed all 163 tests. Python compilation, i18n audit, split-contract audit, `git diff --check`, and CRLF checks passed.
- Modified source files decreased by 826 net lines before adding focused tests and this history entry.

### Manual Media Checks Still Required

- Open the generated SPY×FAMILY SUP over the source video and inspect moving signs, fades, karaoke, boundaries between adjacent events, colors, and forced flags. A hardware-player or authored-disc check is still valuable for the compatibility path.
- Refresh an SP table containing single-frame menu clips and an IGS menu source; verify automatic selection and extracted menu images in the GUI.
- Exercise a VC-1 or MPEG-2 Blu-ray clip so the explicit ffprobe frame-rate fallback is covered with real media.

## Post-Phase 6 — Stabilization and Structural Cleanup

Date: 2026-07-25
Commit: Included in this change

### Scope

Corrected failures found while validating the completed refactor, made SP scan readiness an explicit launch boundary, and removed migration-era entry points and an obsolete Qt-dependent chapter path. The current request-based Remux, Encode, and Add Chapters workflows remain the only execution paths.

### SP Scan and Task Launch

- The visible Remux/Encode tables can finish loading before the background SP worker has scanned every row. Before Phase 6, native timing could take about 3.1 seconds per M2TS; a table with hundreds of SP rows could therefore remain active for minutes even though the main interface looked complete.
- The old `_sp_scan_in_progress` flag represented thread cleanup rather than result readiness. Earlier launch code could consequently report `SP track scan is still running` after the visible load completed; removing that check entirely allowed the opposite race, where a task could capture partially scanned SP rows.
- Task snapshot creation also rebuilt the SP table and started a second scan after the Execute-button readiness check, then immediately captured the request. This caused the first launch to report a missing track selection while the second scan was still filling rows. Launch snapshots no longer refresh GUI tables; the Execute boundary waits for an active scan and reports the exact row if a completed table still lacks captured track configuration instead of silently starting another full scan.
- Scan result readiness, worker identity, thread cleanup, pending launch, and scan failure are now separate states. The worker's already calculated track selection is applied directly without probing the same MPLS again on the GUI thread. A Remux or Blu-ray Encode click during the current scan is queued, and result completion is applied before the scan thread may stop. A successful scan and output-name recomputation resumes that exact function once; failure or cancellation does not start it.
- Results and completion/failure signals from a replaced worker are ignored. A failed scan remains invalid after its thread exits, so clicking Remux again cannot bypass the failure; refreshing the source starts a new scan and clears the failure only when that scan is valid.

### Other Corrections

- Shared SP FLAC conversion now accepts output only when decoding and encoding return success and create a non-empty file. A partial standalone-FLAC output is removed before the visible level-8 FFmpeg fallback, and a failed fallback cannot leave a false checkpoint.
- Remux-input Encode resume now treats only non-empty main/SP files, or the expected directory output for a directory source, as completed checkpoints. Empty files and wrong path types fail before encoding instead of being skipped. External subtitles and companion files still follow their documented file-exists resume rule.
- Manual chapter, attachment, and track extraction now report missing tools and failed commands, use the shared argument-list command entry, validate both exit status and created output, and remove failed temporary output.

### Structural Cleanup

- Removed unused `src.gui`, `runtime.gui_runtime`, and `exports.bdmv_parser` migration facades. No repository entry point, test, build script, or documentation imported them.
- Removed the unused Qt table-to-service chapter API and its filename-based `BD_Vol_NNN` grouping path. That path contradicted the established Add Chapters behavior, where externally supplied MKV files are matched to selected MPLS rows in current sorted order.
- Removed duplicate worker/service copies of track-selection and track-language request state; current jobs continue to receive both configurations explicitly from the immutable request.
- Regenerated both IDE base contracts after removing the obsolete methods and adding the SP lifecycle state.

### Documentation and i18n

- Recorded the actual Phase 6 commit as `ef9ea71` in both status tables and Phase 6 entries.
- Clarified in both README versions that Remux-input Encode resumes from non-empty main/SP checkpoints and rejects empty or type-mismatched paths.
- Added Simplified Chinese mappings for the SP wait/failure states and MKV extraction errors; source strings and comments remain English.

### Verification

- The complete repository run passed all 178 tests, including snapshot-without-refresh, queued SP launch, one-time resume, worker track-result reuse, missing-selection reporting, Remux-source Encode isolation, failed-scan blocking, stale-worker rejection, FLAC partial-output cleanup, invalid Encode checkpoints, and MKV extraction failures.
- Python compilation, source-import checks, i18n audit, split-contract verification, `git diff --check`, and CRLF checks passed.
- Two consecutive split-contract generation runs produce identical base files.

### Manual Media Checks Still Required

- Drag a large multi-disc source into Remux, click Execute while the SP scan is active, and confirm the task starts exactly once after the scan finishes. Then refresh or switch sources during a scan and confirm the replaced worker cannot alter the new table.
- Exercise an actual SP scan failure and confirm Remux remains blocked until the source is refreshed successfully.
- Resume a Remux-input Encode with valid completed outputs, an empty main/SP output, and a wrong-type path; verify only valid checkpoints are skipped.
- Run real standalone-FLAC success/failure fallback and manual MKV chapter/attachment/track extraction checks with the configured tools.

## Post-Phase 6 — Deterministic Audio Cleanup Restoration

Date: 2026-07-25
Commit: Included in this change

### Scope

Restored the required silent-track, duplicate-track, and DTS/FLAC size decisions in the shared final audio pipeline without restoring output-directory discovery or filename-based track guesses.

### Logic Changes

- Final Blu-ray Remux and Encode muxing now analyzes every selected audio track. Remux performs cleanup even when lossless-to-FLAC conversion is disabled; Blu-ray Encode staging still leaves audio untouched and runs cleanup only after video encoding succeeds.
- One `mkvextract` invocation extracts every selected audio track from the source Matroska into the task folder. Analysis and conversion reuse those files, so the large source container is no longer reopened once per track.
- One FFmpeg pass per extracted track calculates full-track `volumedetect` maximum volume and a SHA-256 fingerprint of deterministic 8 kHz PCM. A maximum below -60 dB removes the track as silent. Extraction or analysis failure is explicit, and the required MKVToolNix and FFmpeg executables are checked before work when the source boundary permits it.
- Duplicate comparison is limited to the same source codec family, channel count, and decoded fingerprint. Tracks with different known languages remain separate. A confirmed duplicate removes the later track and retains the earliest source-order track, so later conversion and final `mkvmerge --track-order` construction use one explicit kept-track list.
- The implementation operates on captured Matroska track IDs. It does not scan the output directory, infer ownership from `.track` filenames, or inspect unrelated residual files.
- DTS-family FLAC output now replaces the source only when it is no larger than the extracted DTS. A larger FLAC is deleted and the original DTS remains in its exact position; successful PCM and TrueHD/MLP FLAC output remains FLAC regardless of size.

### Documentation and i18n

- Both README versions explain automatic cleanup, the -60 dB threshold, duplicate boundaries, retained order, terminal reporting, one-pass extraction, full-track analysis time, and the Encode staging boundary.
- Both code-standard versions record automatic cleanup as the explicit documented exception to retaining every selected GUI track and require one-pass selected-audio extraction.
- Added bilingual extraction, analysis, progress, failure, silent-removal, duplicate-removal, and DTS-size-fallback messages.

### Verification

- Added focused coverage for single-command multi-track extraction, silent removal, same-language duplicate removal, different-language and different-channel preservation, retained source order, cleanup with Remux FLAC conversion disabled, Encode staging isolation, DTS/FLAC size fallback, TrueHD/MLP size behavior, analysis parsing, and missing-FFmpeg/mkvextract preflight.
- The complete repository run passed all 188 tests. Python compilation, i18n and split-contract audits, `git diff --check`, and CRLF verification passed.
- A real-tool synthetic Matroska check used two same-language identical FLAC tracks, one different-language identical FLAC track, and one silent FLAC track. One `mkvextract tracks` command extracted all four selected tracks; subsequent FFmpeg commands read only those temporary FLAC files. Analysis removed the later same-language duplicate and the -91 dB silent track, and MKVToolNix verification retained English and Japanese FLAC in the planned order.

### Manual Media Checks Still Required

- Run Remux on a disposable output using a disc with known silent and duplicated tracks. Compare `mkvmerge -J` track order, codec, language, channel count, flags, and delay against the GUI selection, confirming only the documented tracks are removed.
- Repeat with FLAC conversion disabled, and with an Encode task, to verify final cleanup while the Blu-ray staging MKV retains all selected source audio.
- Measure full-track analysis time on a title with several long audio tracks. The source disc is read-only; only the chosen output and task-owned temporary files may be changed.

## New Feature — Application Settings

Date: 2026-07-26
Commit: Included in this change

### Scope

Added a complete application-settings system: versioned configuration,
window/UI-state persistence, startup and encoding defaults, editable external
tool paths, and a manual GitHub Release update check.

### Structural Changes

- Added `src/core/app_config.py` with frozen preference records, schema
  validation, source/frozen path resolution, first-run template loading, and
  atomic sibling-file replacement.
- Added tracked `config.default.json` and ignored the writable root-level
  `config.json`. Frozen builds package the default template under `_MEIPASS`,
  while the running application creates and updates `config.json` beside the
  executable.
- Added a standalone settings dialog with General, Paths, Advanced, and
  External Tools pages. The External Tools page edits the effective
  `src/core/settings.py`, validates Python syntax, and saves it atomically.
- Frozen builds package the settings source as a template, seed an editable
  copy beside the executable, and load it as an override on the next launch.
- Extended the configuration with validated audio, Remux, and Encode
  preferences. Existing schema-version-1 files without the new sections load
  with backward-compatible defaults.
- Centralized the built-in x264, x265, and SVT-AV1 preset maps, plus the
  application-owned version and title.
- Added a settings/state GUI mixin, regenerated the GUI base contract, and
  removed state that could not distinguish Remux, Encode, and DIY output pages.
- Added immutable `AudioEncodingSettings` to Remux/Encode requests and threaded
  it through main, SP, direct-audio, and final-mux workflows.
- Added an asynchronous Qt request for GitHub's latest published full Release.

### Behavior Changes

- Clean window close stores Qt window geometry, language, theme, font size, and
  opacity. Successfully restored geometry bypasses first-run fitting and
  centering.
- Configured startup page, Series/Movie mode, Remux/Encode output folders, and
  Encode/Remux defaults initialize visible controls. Tasks continue to capture
  current visible values instead of rereading configuration.
- Remux, Encode, and DIY retain independent output-folder values during the
  current session.
- Invalid configuration is reported and kept unchanged. A successful explicit
  save can replace it; an ordinary close cannot overwrite a failed load.
- Language selectors use native names, and dark-mode tabs have readable text
  with distinct hover and selected backgrounds.
- Standalone and FFmpeg FLAC levels default to 8 and are independently
  configurable from 0–8 and 0–12. Standalone FLAC detects logical CPU threads.
- FDK-AAC and Opus value 0 keeps automatic behavior; positive values are
  explicit kbps targets. The settings page includes bitrate guidance.
- The External Tools page checks active paths, lists missing tools, and points
  users to the platform setup script.
- Manual update checks read only the GitHub Release `tag_name`, compare numeric
  versions asynchronously with a 15-second timeout, and never download files.
  A newer result links to GitHub Releases and reminds the user to copy
  `config.json` to the new program directory.

### Documentation and i18n

- Updated both README and code-standard versions with configuration placement,
  first-run behavior, settings boundaries, audio defaults, update checking, and
  continued visible-GUI authority.
- Added English/Simplified Chinese text for all settings controls, guidance,
  validation, persistence, external-tool, and update states.

### Verification

- Added focused coverage for configuration creation/loading/validation,
  persistence and frozen paths, settings-dialog editing, startup initialization,
  audio command values, external-tool detection, version comparison, manual
  request start, release linking, and the `config.json` migration reminder.
- The complete repository run passed all 208 tests. Python compilation, i18n
  and split-contract audits, `git diff --check`, and CRLF verification passed.

### Manual Checks Still Required

- Build and launch the Windows one-folder package from a writable disposable
  directory. Confirm packaged templates seed `config.json` and editable
  `src/core/settings.py` files beside the executable.
- Check window geometry on single- and multi-monitor layouts, all settings in
  both languages, invalid/unwritable configuration handling, and every startup
  encoder/bit-depth/default combination.
- Temporarily configure a missing external tool and confirm the correct setup
  script guidance, then restore the path.
- Check updates once offline, once at the current version, and once against a
  temporarily lower local version. Confirm the dialogs and external link.
- Run short disposable Remux/Encode samples with non-default and automatic
  audio values, then inspect terminal commands and final Matroska metadata.

## Encoder Toolchain Migration — Official x264/x265

Date: 2026-07-28
Commit: 26dc5fe

### Scope

- Migrated both setup scripts and Docker from third-party encoder forks to the current official upstream x264 and x265 sources while preserving `C:\Software\x264.exe`, `C:\Software\x265.exe`, `/usr/bin/x264`, and `/usr/bin/x265`.
- x264 resolves the latest official `master` revision each time; x265 resolves the latest official stable numeric release tag. Neither encoder is pinned to a version or commit.
- Switched x265 checkout to the official `Multicorewareinc/x265` GitHub repository.

### Removed Paths and Behavior Changes

- Removed the Windows jpsdr/t_mod prebuilt x264 download and the Yuuki-Asuna x265 fork checkout.
- Removed the x265 source-rewriting workaround. The unmodified official source is configured with `CMAKE_POLICY_VERSION_MINIMUM=3.10`; integrations unused by that migration are disabled explicitly.
- Removed the fork-only `--pme` and `--pmode` options from the x265 Extreme preset. No compatibility path remains for those old options.
- Windows compiles official x264 with the MSYS2 UCRT64 toolchain, all supported bit depths/chroma formats, LTO, and the upstream `fprofiled` target. Its post-install capability probe uses the official `--colormatrix` spelling so a valid build is not rejected. Windows x265 remains a static 8/10/12-bit MSVC multilib build.
- Linux builds the dynamically resolved official sources. Docker remains a single Ubuntu 26.04 image and replaces the x265 and x264 build steps at their original corresponding locations. Remote official metadata at each position forms the Docker cache key, so a new encoder revision invalidates only that encoder layer and the layers after it.

### Documentation and Standards

- Updated both README versions and `legal/THIRD_PARTY_NOTICES.md` with the dynamic official-version policy, unchanged executable paths, replacement-in-place guidance, and custom x265 build references.
- Added matching bilingual code standards requiring the latest official software by default, defining Dockerfile as the Ubuntu 26.04 Linux-setup adaptation, and requiring cache-preserving Dockerfile edit placement.

### Verification

- PowerShell parsing and `bash -n` validate the setup scripts; focused regression tests cover dynamic official-source resolution, multilib builds, Docker layer placement, unchanged executable paths, and removed fork-only options.
- Docker is not installed on the verification host, so the image was not built locally. Build it on a Docker host and inspect both version banners and the x265 `8bit+10bit+12bit` output.
- Run each setup script on a disposable supported host, then encode short 8/10-bit x264 and 8/10/12-bit x265 samples, including an HDR10 sample, before publishing binaries.

## HDR10+ Build Environment Preparation

Date: 2026-07-28
Commit: `56ce8bb` (`build(hdr): enable x265 HDR10+ and add hdr10plus_tool`)

### Scope

- Enabled x265's native HDR10+ JSON parser in the final 8-bit multilib CLI while keeping it disabled in the linked 10-bit and 12-bit core libraries to avoid duplicate parser objects.
- Added the latest official `hdr10plus_tool` release to both setup scripts and Docker without adding a local Rust build. Windows uses the official x86_64 MSVC archive; Linux and Docker select the official x86_64 or AArch64 musl archive.
- Added `HDR10PLUS_TOOL_PATH` to shared settings, the External Tools page, the Windows one-folder package, and the existing fixed system layouts: `C:\Software\hdr10plus_tool.exe` and `/usr/bin/hdr10plus_tool`.
- Kept the x265 flag changes in the existing x265 Docker layer and placed the new tool's release layer near the end of the Dockerfile.
- Added the same narrowly scoped compatibility edit to all managed x265 builds: insert the missing `<cstdint>` include in upstream `dynamicHDR10/json11/json11.cpp` before compiling the native HDR10+ parser.
- This change prepares the managed environment only; automatic HDR10+ extraction and x265 command planning remain a separate follow-up.

### Compatibility and Verification

- Upstream release automation builds Linux artifacts for the musl targets with the internal-font feature and no system fontconfig dependency. The official 1.7.1 x86_64 artifact was additionally inspected as a stripped static PIE, so it can run directly on Ubuntu 22.04 without a glibc-version dependency.
- x265 setup verification now requires both the 8/10/12-bit build banner and the native `--dhdr10-info` help entry, causing an older same-version managed build without HDR10+ to be rebuilt. Help text is captured independently because x265 returns a non-zero status after printing it.
- Linux x265 configuration, compilation, linking, library merging, and installation now return immediately on the first failed command instead of continuing with secondary missing-file errors.
- Verification uses the current official x265 4.2 tag and includes a complete 12/10/8-bit multilib CLI build with native HDR10+ enabled.
- PowerShell parsing, `bash -n`, 60 focused build-environment tests, three External Tools settings tests, `git diff --check`, and line-ending checks passed. Docker was unavailable on the verification host, so a complete image build remains a manual check.

## Automatic HDR Metadata and Encode Row Reliability

Date: 2026-07-29 to 2026-08-01
Commit: `bbd8813` (`feat(encode): complete automatic HDR metadata workflow`)

### Source Discovery and Static Metadata

- Completed the automatic HDR path from per-row source discovery through final Matroska verification, together with the row-result and artifact rules needed for long Encode batches.
- Each row probes the media actually loaded by its final VPy: a direct Remux MKV, the task-owned Blu-ray staging MKV, or the Dolby Vision base-layer HEVC prepared for x265. The probe runs after source preparation so it cannot inspect a Blu-ray root, MPLS, or superseded container.
- One FFprobe call reads the first video stream and first frame. First-frame side data is merged without duplicates because static HDR SEI may be absent at stream level. Missing HDR fields remain valid; the probe records the available stream and codec without premature classification.
- Source-probe and metadata-planning failures are non-blocking. Encoding continues with the user's arguments, creates a numbered non-overwriting `<output-name>.hdr-metadata-error.txt`, and reports the warning once after Worker cleanup.
- One parser normalizes range, primaries, transfer, matrix, chroma location, mastering display, and MaxCLL/MaxFALL for all encoders and input types. x264 receives its supported color options plus `--mastering-display` and `--cll`; x265 uses `--master-display` and `--max-cll`; SVT-AV1 receives H.273 values and converted mastering coordinates and physical luminance.
- Visible manual parameters remain authoritative. A manual option suppresses only its automatic counterpart; x264 `--fullrange` also suppresses range, while x265 `--video-signal-type-preset` suppresses all automatic color/static-HDR options. The program does not infer `--hdr10` or `--hdr10-opt`, and skips malformed or unsupported individual values.
- After the final VPy is prepared, output 0's first, middle, and last frames are sampled. Stable VapourSynth range, primaries, transfer, matrix, and chroma properties override source values; missing properties fall back to FFprobe. Inconsistent samples fail only that row.
- A VPy primaries or transfer change drops source mastering-display/CLL data and disables Dolby Vision preservation so stale metadata is not attached to changed pictures. Other VPy probe failures retain the source snapshot through the warning path.

### HDR10+, Dolby Vision, and x265 Capability Compatibility

- ST 2094-40 activates automatic HDR10+ handling for x265 10/12-bit output. `hdr10plus_tool` extracts validated JSON whose frame count and source frame rate must match the VPy timeline. Manual `--dhdr10-info` remains authoritative.
- The actual configured or bundled x265 is probed for `--dhdr10-info`, `--dolby-vision-profile`, and `--dolby-vision-rpu`. Results are cached by normalized path, size, and modification time, so replacing a custom build invalidates the cache without relying on a version string.
- The External Tools settings check reuses that probe: `hdr10plus_tool` is required only when x265 advertises `--dhdr10-info`, and `dovi_tool` only when both Dolby Vision input options are present. Builds without the corresponding capability do not produce a missing-helper warning.
- Native arguments are passed only when advertised. Missing or unverified native HDR10+ uses verified, atomic `hdr10plus_tool` post-injection; Dolby Vision uses checked `dovi_tool` injection. An active RPU is verified again after HDR10+ injection, and a failed HDR10+ replacement leaves the original encoded stream untouched.
- Native Dolby Vision writing requires x265 10/12-bit output plus both existing VBV options and mastering-display metadata. The program never invents VBV values. Without those prerequisites, the extracted Profile 8.1 RPU is injected after encoding.
- HDR10+ and Dolby Vision share one x265 encode only when both native paths and all Dolby Vision prerequisites exist. Both metadata sets are checked after the last injection and before muxing. x264 and x265 8-bit reject requested Dolby Vision; SVT-AV1 continues without it because the current toolchain cannot author AV1 Profile 10.
- Managed x265 enables `ENABLE_HDR10_PLUS` in every linked core and advertises both Dolby Vision inputs. Its marker replaces older same-version managed builds missing those capabilities, while runtime probing preserves compatibility with independently compiled binaries.
- Extraction, timeline, or verification failure keeps the normal static-HDR encode and retains useful non-empty JSON/RPU artifacts under the row policy. Verified temporary metadata is removed only after successful final muxing.

### Final Verification and Row Reliability

- After the formal MKV is published, FFprobe compares only static fields supplied automatically; manual GUI values are not judged against source metadata. Active HDR10+ is rechecked on the MKV, and active Dolby Vision must report Profile 8 with an RPU frame count matching VPy output.
- A final-container metadata mismatch retains the MKV, aggregates all failures into one non-overwriting HDR report and row warning, marks the row complete with warnings, and lets later rows continue. Failed encoding, broken intermediates, and failed final muxing remain row failures.
- Every row records source, planned output, status, warnings, report path, and retained artifacts. After request-wide preflight, encoder, Dolby Vision, copy, audio-conversion, and final-mux failures are isolated to the affected row and create a numbered `<output-name>.encode-error.txt`; later visible rows continue.
- Elementary streams use collision-resistant `.partial.<id>` names. Non-empty streams, partial containers, audio work files, HDR10+ JSON, RPU data, and partial injected streams survive row failure or cancellation and are listed in the report. Zero-byte files are removed; successful rows clean only their own artifacts.
- Cancellation still stops all remaining rows and does not become an ordinary failure. Unsafe request-wide conditions still stop before execution. Blu-ray staging remains when any row fails, and the GUI presents one aggregate result only after Worker cleanup.

### Redundant or Conflicting Paths Removed

- Reused one actual-source probe, parser/planner, HDR10+ verifier, Dolby Vision extractor, warning writer, and row outcome model. Separate per-input metadata paths, duplicate dynamic-metadata command paths, and the first draft's reverse CLI-mapping table were removed or not retained.
- Removed delete-on-encoder-failure and unconditional Dolby Vision cleanup. Row exceptions now use one result/report boundary, while cancellation and request-wide safety remain explicit batch stops.
- Final static, HDR10+, and Dolby Vision failures share one warning/report. Checks before and after injection or final mux remain separate because they validate different artifacts.

### Documentation and Verification

- Synchronized both README versions, relevant Wiki pages, and bilingual i18n for discovery, planning, dynamic metadata, row outcomes, reports, and final verification.
- Focused coverage includes source selection and probe failure, encoder mappings and manual precedence, VPy changes, row continuation/cancellation and artifact retention, native and post-injected HDR10+/Dolby Vision, custom-x265 and settings-path capability checks, and final-container warnings. The final repository run passed all 240 tests; Python compilation, i18n and split-contract audits, diff checks, and line-ending checks passed.
- Real-tool checks wrote BT.2020/PQ metadata with current x264, x265, and SVT-AV1; probed a three-frame VapourSynth R57 script; rejected an older x265 that omitted HDR10+; and confirmed the rebuilt x265 wrote nine HDR10+ and nine Profile 8 RPU frames into one stream.
- An official 259-frame fixture verified post-injection without losing Profile 8 RPU data. Its final MKV passed static HDR, HDR10+, Dolby Vision Profile 8, and 259-frame RPU verification together.

### Manual Media Checks Still Required

- Run short GUI Encodes from representative Remux, Blu-ray, and Dolby Vision sources; confirm actual-source reporting, final static signaling for each encoder, and manual-parameter precedence.
- Use disposable VPys that change primaries/transfer and vary sampled properties; confirm stale metadata removal, row-local failure for inconsistent samples, and later-row continuation.
- Exercise HDR10+, Dolby Vision, and combined output with and without native VBV prerequisites. Repeat with a disposable custom x265 lacking native dynamic-metadata options, then restore the intended binary.
- Deliberately fail source probing, planning, final verification, encoding, injection, audio/final muxing, and one multi-row cancellation. Inspect retained outputs/artifacts, numbered reports, Blu-ray staging, later-row behavior, and the single post-cleanup summary.

## Settings-Driven Linux Setup and Aligned Docker Tool Placement

Date: 2026-08-01
Commit: `c2552ad` (`feat(setup): install Linux tools at configured paths`)

### Scope and Logic Changes

- Linux setup now loads all managed executable and VapourSynth plugin destinations from `src/core/settings.py` after Python is available, validates the complete path set, and verifies every configured tool before reporting success.
- Source-built and downloaded tools install at their configured destinations. FFmpeg, FFprobe, and MKVToolNix executables supplied by packages are copied to their configured destinations after installation.
- Docker installs every managed tool directly at the default Docker path declared by the Linux branch of `settings.py`. Existing build sections remain authoritative; FLAC is now copied from its `/usr/local` build prefix to the configured `/usr/bin/flac` destination within the FLAC section.
- Corrected the Linux tsMuxer setting name from the unused `TSMUXER_PATH` variant to `TS_MUXER_PATH`; the settings page and runtime fallback now use the single canonical name.

### Redundant or Conflicting Paths Removed

- Removed hard-coded destinations from Linux setup for x264, x265, SVT-AV1, fdkaac, FLAC, tsMuxer, dovi_tool, hdr10plus_tool, truehdd, vspipe, vsedit, and the VapourSynth plugin directory.
- Removed the Linux-only tsMuxer setting-name branch and the service compatibility lookup for the misspelled variable.
- Removed obsolete environment-variable examples that repeated the old fixed Linux paths at the end of the setup script.

### Documentation, Verification, and Deferred Work

- README behavior remains unchanged because the documented paths were already the defaults. Updated both code-standard versions; no user-visible application text or i18n catalog entry changed.
- `bash -n setup_linux_environment.sh`, 11 focused setup/source-integrity tests, and all 241 repository tests passed. `git diff --check` and final line-ending checks are part of this change's final verification.
- A real Linux setup run with temporary custom paths and a complete Docker image build remain manual checks; both write installed tools to the configured destinations and should be run only on a disposable host or image. No implementation work is deferred.

## Same-Frame Encode Comparison Images

Date: 2026-08-01
Commit: `f632d85` (`feat(encode): add same-frame comparison images`)

### Scope and Logic Changes

- Swapped the Encode-page positions of the lossless-audio selector and getnative checkbox while keeping them on separate rows. Added a default-enabled **Output comparison images** checkbox immediately after getnative and a matching Advanced-setting preference.
- The current checkbox value is captured in `EncodeSettings`. After each video output succeeds, Encode determines the midpoint of the frame range shared by the source and encoded files, then invokes FFmpeg twice with the same zero-based frame-selection expression.
- Each pair is written under `<selected output>/<source folder name>/Compare` as `NNN-output-fNNNNNN-source.png` and `NNN-output-fNNNNNN-encoded.png`. Output stems are limited to 40 characters and row prefixes keep names distinct without creating per-file folders.
- Valid comparison pairs are reusable for resumable Remux-source Encode. A media-specific screenshot failure is reported as a row warning and does not delete the successfully encoded video.

### Validation and Documentation

- Comparison-image preflight requires both configured FFmpeg and FFprobe executables. Automated coverage verifies saved defaults, GUI row placement, request capture, actual output-directory placement, paired filenames, and identical frame-number filters without timestamp seeking.
- Updated both README versions, the Simplified Chinese translation catalog, and both code-standard versions. No obsolete compatibility path was retained.
- Focused configuration, Encode workflow, worker-boundary, i18n, and split-contract checks passed, as did all 242 repository tests. A live FFmpeg check extracted frame 5 from two losslessly equivalent 10-frame files with the production filter and produced byte-identical PNGs; final diff and line-ending checks also passed.
- A real-media Encode remains a manual check: use a disposable output directory, verify the two PNGs show the same source/encoded frame, and inspect SDR and HDR screenshot appearance under the generated `Compare` folder.

## Duration-Adaptive Automatic Black-Border Cropping

Date: 2026-08-01
Commit: `7d80a4d` (`feat(encode): add automatic black-border cropping`)

### Detection and VapourSynth Integration

- Added an opt-in Encode checkbox and matching Advanced default. Every enabled batch reports that automatic black-border analysis is heuristic and that the encoded picture must be checked.
- Each row probes video dimensions and duration, then performs stratified pseudo-random FFmpeg input seeks without writing screenshots. The sample count is one point per 150 seconds, clamped to 4–24, and each point decodes three nearby frames for `cropdetect`.
- Valid detected active rectangles are combined by union, producing one even-aligned fixed crop that cannot remove pixels used by any sampled frame. Changing borders therefore reduce or eliminate the crop rather than creating time-varying output dimensions.
- A managed `src8.std.Crop(...)` block is inserted before downstream processing in the row's VPy. Repeated rows replace the block, disabling the option removes it, and scripts without a known safe clip boundary fail explicitly.

### Dynamic HDR Metadata

- Dolby Vision preparation now extracts the converted profile 8.1 RPU to a source artifact, exports its L5 editor configuration, subtracts the physical crop from every active-area preset, writes a task-owned edited RPU, and verifies that it remains profile 8.
- The same edited RPU path is supplied to native x265 Dolby Vision writing and to the existing verified post-injection fallback. A manual `--dolby-vision-rpu` is rejected when a nonzero automatic crop is active because the program cannot safely rewrite an externally owned RPU.
- HDR10+ metadata remains on the existing extraction/native-or-injection path without an additional crop-specific prompt.

### Documentation, Verification, and Manual Checks

- Updated both README versions, the Encode/VapourSynth, Dolby Vision, and developer Wiki pages, bilingual i18n, and configuration/GUI contracts.
- Focused tests cover adaptive counts, deterministic stratified timestamps, fast-seek command construction, conservative rectangle union, managed VPy replacement/removal, saved GUI settings, Dolby Vision L5 preset edits, and the processed RPU path used by native x265.
- All 252 repository tests passed, together with Python compilation, i18n and split-contract checks. A real FFmpeg smoke test generated a 320x240 source with 30-pixel top/bottom bars and the production detector returned the expected 320x180 active picture.
- A real-media check remains required: test short and feature-length constant-border, variable-border, dark-scene, HDR10+, and Dolby Vision sources; inspect reported margins and output dimensions; and verify the final Dolby Vision RPU with `dovi_tool`.

## Read-Only Built-In and User-Defined Encode Presets

Date: 2026-08-01
Commit: `d41ac01`

### Configuration and Preset Ownership

- Removed the built-in `Custom` entry. `src/core/encode_presets.py` now owns only the four read-only built-in parameter sets for each encoder, while typed user presets carry an encoder, editable name, and editable parameter string.
- Application configuration no longer stores a separate default parameter string. It stores only the selected preset name and actual user-defined preset entries; built-in names and parameters are never copied into `config.json`.
- Existing configurations retain meaningful edits: a legacy `Custom` selection or a built-in preset whose saved parameters differ from the current built-in value is migrated into a selected user preset. Matching legacy built-in parameters are discarded as redundant.
- Configuration validation rejects empty user names, duplicate names within one encoder, built-in-name collisions, unsupported encoder ownership, and a selected default that does not exist for the selected encoder.

### GUI Behavior

- The Encode-page preset combo is rebuilt from the current encoder's built-in and user-defined presets. Changing encoders removes presets owned by other encoders; changing a preset fills the parameter field, but directly editing that field no longer changes the selected preset name.
- Advanced settings replaces the multi-line default-parameter editor with a compact preset manager: one preset selector, Add/Delete buttons, one name line, and one parameter line. Built-in entries can be inspected but their fields are read-only and Delete is disabled; user entries can be added, renamed, edited, and deleted.
- The startup preset resolves its current parameters from the selected built-in or user preset. Saving settings refreshes the available Encode-page preset names without overwriting the current session's visible parameter string.

### Redundant Paths Removed, Documentation, and Verification

- Removed automatic switching to `Custom`, the empty `Custom` parameter entries duplicated across three encoders, the editable default-parameter control, and persisted `preset_parameters` from newly saved configuration.
- Synchronized both README versions, the Encode/VapourSynth Wiki, bilingual code standards, and i18n. Focused configuration and GUI tests cover persistence, legacy migration, encoder filtering, built-in protection, startup resolution, and stable selection during direct parameter edits.
- All 256 repository tests passed together with Python compilation, i18n, and split-contract checks. An offscreen Advanced-settings render confirmed the compact one-line name/parameter layout and enabled-state distinctions.
- A short real-media Encode with one built-in and one user-defined preset remains a manual check. It writes normal encoded outputs, so use a disposable output directory and verify the emitted encoder command matches the visible parameter field.

## Automatic Getnative Analysis and Kernel Fidelity

Date: 2026-08-02
Commit: a5fa237

### Execution and Detection Corrections

- Retained the split runtime required by the application's system Python and portable Python 3.13 VapourSynth: the system-side module owns curve and multi-frame ranking, while `getnative.vpy` owns image loading, descale/rescale evaluation, and metric collection under `vspipe`.
- RGB sample PNGs now follow the upstream BT.709 RGB-to-luma conversion before becoming 32-bit `GRAYS`. The previous path selected RGB plane 0 directly, so it measured the red channel rather than image luminance when L-SMASH loaded FFmpeg PNGs as `RGB24`.
- The prioritized scan still reports all 16 configured kernels. The first three priority kernels always receive a fine scan; later kernels skip that scan only when their comparable half-size coarse score is clearly weaker. Invalid or incomplete curves cannot win a kernel or affect the global best.
- Kernel consensus requires the configured number of complete, valid curves within a real 2-pixel window and cannot stop before `min_kernels`. The automatic Encode caller attempts all 16 kernels and streams even the explicitly skipped screen results.
- Winner verification still exposes the strict decreasing-ratio diagnostic, but automatic ranking uses the established permissive curve-valid flag so scarce usable samples are not discarded. Multi-frame aggregation groups rounded heights and ranks each group by the top three `min(score, 2) × normalized_height⁴` weights. The score saturation keeps a low-noise false notch from overwhelming an otherwise strong group while still allowing a high-resolution singleton to win when usable samples are sparse.
- Curve selection once again uses Infiziert90/getnative's adjacent-height error drop as its primary notch signal and returns the directly comparable `previous_error / current_error` ratio as the cross-frame score. The prior smoothed-valley floor remains only as a broad-notch fallback; 540p, post-1040p, local-oscillation, and unstable-tail exclusions apply before either result can win.
- The confirmed 535p-through-545p exclusion remains mandatory across primary, fallback, and segment-refinement selection, and candidates above 1040p are now unconditionally rejected. The existing oscillating-tail suppression remains active below that boundary; genuinely native 540p material remains a manual VPy case.

### Runtime Application, Performance, and Ownership

- Generated Encode VPy files now apply the exact detected kernel: all eight Bicubic parameter pairs, Lanczos taps 2–5, Bilinear, and Spline16/36/64. The previous template fixed every Lanczos result to taps 3, fixed every Bicubic result to b/c 1/3, and sent Spline results through the Bicubic branch.
- Each sample's VapourSynth executor uses one frame worker. Each incremental analysis round may launch up to 20 sample processes, capped by the logical CPU count and available physical memory at a fixed 800 MiB budget per sample after a system reserve. Extraction starts with only the current round rather than 100 frames up front, and expands toward the 100-sample safety ceiling only while the usable-curve target is unmet.
- All 16 two-stage kernel scans for one sample now share one VSPipe lifecycle. A JSONL progress sidecar reports every completed kernel immediately, while the parent consumes completed sample futures as they arrive rather than buffering them until every process in the round exits.
- The broad step-4 kernel screen uses a centered half-size crop before a full-frame ±20p fine scan. The winner is then rechecked by a full-frame step-4 curve and another full-frame ±20p 1p scan instead of a 627-point full-resolution curve; VapourSynth's frame cache is capped at 256 MiB and numerical-library worker pools stay at one thread.
- FFmpeg sample extraction now uses checked argument-list commands and round-specific filenames. L-SMASH image loading disables persistent indexes, while task-owned sample and debug directories are removed by exact path.
- Removed the unused runtime VPy creator and the broad cleanup routine that recursively deleted configured debug roots and matching current-directory files regardless of task ownership.

### Documentation, Verification, and Manual Checks

- Updated both README versions, the Encode/VapourSynth Wiki, both code-standard versions, and the Simplified Chinese i18n catalog. Added focused regression coverage for kernel minimums, complete-curve consensus, permissive frame acceptance, empirical multi-frame ranking, the 540p and post-1040p exclusions, the 20-process cap, exact debug cleanup, RGB-luma loading, and exact VPy kernel application.
- All 272 repository tests passed together with Python compilation, i18n and split-contract checks. Portable Python 3.13/VSPipe smoke tests returned all 16 unique kernels, streamed per-kernel progress, and reproduced the expected 892p adjacent-error notch from an FFmpeg-generated RGB PNG through the production split boundary.
- Three complete 20-sample runs used `Cyberpunk Edgerunners` Disc 1 `00000.m2ts`. The first full-frame-coarse pass took 1661.14 seconds and exposed the smoothed-valley 887p defect; the half-size coarse pass took 946.78 seconds, reducing wall time by 42.99%, and retained 19 usable samples with about 17.3 GiB peak total worker memory in the worst full-frame phase. The final upstream-ratio run took 963.26 seconds; replaying its unchanged 19 final curves through the finalized saturated multi-frame weight selected the eight-sample 892p group, Bilinear, and confidence 3.556979. Five remains only the minimum required before skipping another round: every usable result from the already-launched 20-sample round is retained.
- A complete 20-sample run on `2.5 Dimensional Seduction` Vol.1 `00003.m2ts` finished in 731.79 seconds and selected the expected 900p with Spline16. All 320 kernel events were emitted, eight clearly weaker kernels skipped their fine scan, and 19 curves were usable: 15 resolved exactly to 900p, with no systematic 5p offset. Peak combined Python/VSPipe working set was 15.33 GiB; the single-VSPipe transient maximum was 1014.8 MiB, while observed final-verification processes stayed near 380–400 MiB. Isolated measurements put the 16-kernel and final-verification peaks at 494.1 MiB and 412.6 MiB respectively.

## Cross-Platform Default VPy Source and Rescale Safety

Date: 2026-08-02
Commit: Included in this change

### Source and Plugin Corrections

- Linux setup now captures the complete `ldd -r` report before checking unresolved symbols. The previous `pipefail` plus `grep -q` pipeline could turn a successful match into SIGPIPE status and incorrectly skip the L-SMASH-Works rebuild. FFmpeg 4.x index-access compatibility remains version-gated.
- Linux FLAC setup now checks the source-owned `/usr/local/bin/flac` before the configured runtime path and synchronizes a current source build to that configured path. A stale distribution binary can no longer cause a redundant rebuild or hide the installed source version.
- Generated default scripts load configured plugins before importing `mvsfunc`, use only L-SMASH with a hashed index in the system temporary directory, and contain no source-reader `try`/`except` fallback. The obsolete FFMS2 path was removed from both the generated script and getnative image loading.
- Both Windows and Linux now use `placebo.Deband`. The Windows installer copies `libvs_placebo.dll` from the same verified AmusementClub/tools archive as VSEdit, scripts, and the other required plugins, and verifies the `placebo` namespace in that shared component.

### Default Processing and Preset Changes

- The generated script rejects field-based input explicitly instead of applying a progressive restoration chain to interlaced video. Native inverse scaling now descales only luma, resizes chroma with explicit Blu-ray left chroma location, and uses a reconstruction-difference mask to restore all original YUV planes over credits and other final-resolution composites.
- Advanced settings initialize a new Encode VPy-processing row, while task launch snapshots its visible denoise (`0.0`–`3.0`, default `0.6`), dehalo (`0.0`–`1.0`, default `0.0`), dering (`0.0`–`1.0`, default `0.0`), deband (`0.0`–`1.0`, default `0.5`), and anti-aliasing (`0.0`–`1.0`, default `0.5`) values through configuration, request, service, preview, and the generated script. Defect-specific dehalo and dering start disabled; deband and EEDI2 anti-aliasing now start at the literal blend midpoint and skip their work at `0`. Deband restores multi-plane edge/detail regions through a softened Prewitt mask, and the EEDI2 result is now limited in the correct direction toward the source luma. Custom scripts are changed only when they expose the corresponding top-level numeric assignment.
- The old fixed whole-chain `NLMeans h=3` reference was replaced by spatial luma-only NLMeans with a strong-edge mask and pixel-change limiting. Conservative abcxyz-derived dehalo and MinBlur/HQDering-derived ring-band processing use only the already-required `std`, `rgvs`, `nlm_ispc`, and `mvsfunc` components, so no additional plugin was introduced.
- x264 built-in presets no longer force Level 4.1, allowing their configured reference-frame counts to select a conforming level. SVT-AV1 presets no longer request synthetic film grain by default.

### Documentation and Verification

- Synchronized both README versions, the Encode/VapourSynth Wiki, both code-standard versions, and focused setup/default-VPy regression tests. The Wiki now documents the adjustable restoration stages, distinguishes true interlace, telecine, and mixed cadence, records custom QTGMC/IVTC starting points, and explains that final-resolution text protection is a reconstruction-difference mask rather than OCR.
- Windows, Ubuntu 22.04, and Ubuntu 26.04 each rendered a generated 900p Bicubic default VPy frame using L-SMASH and placebo with no generated `try`/`except`, FFMS2, or neo_f3kdb path. Ubuntu 22.04 also rebuilt and loaded the formerly broken L-SMASH-Works plugin with no unresolved symbols.
- The FLAC selector chose `/usr/local/bin/flac` 1.5.0 on Ubuntu 22.04 and correctly fell back to `/usr/bin/flac` 1.5.0 on Ubuntu 26.04. The installed Windows `libvs_placebo.dll` matched the extracted AmusementClub/tools file byte-for-byte (SHA-256 `A001EC26EFF87E5261E9438B9CBA0ADB176C2B6E210F7CBCD2E6D0F1A8F6F80E`) and evaluated the generated script's exact 16-bit Deband call successfully.
- All 283 repository tests passed together with Python compilation, i18n, split-contract, PowerShell-parser, shell-syntax, diff, and line-ending checks. Windows additionally rendered all 16 getnative kernels and verified the field-based rejection path; the revised adaptive deband and anti-aliasing post-filter also produced a YUV420P16 smoke frame in the managed VapourSynth environment.
