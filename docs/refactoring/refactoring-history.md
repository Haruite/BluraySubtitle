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
| Phase 3.3 | Blu-ray Remux workflow | Complete | This change |
| Phase 3.4 | Blu-ray Encode workflow | Pending | — |
| Phase 3.5 | SP, track alignment, and missing-track repair | Pending | — |
| Phase 3.6 | Audio conversion and Dolby Vision | Pending | — |

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
Commit: Included in this change

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
