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
| Phase 3.6 | Audio conversion and Dolby Vision | Complete | This change |

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
Commit: Included in this change

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
Commit: Included in this change

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
