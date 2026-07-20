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
| Phase 1 | Contract, configuration matrix, and safety baseline | Complete | `d889262` |
| Phase 2 | GUI-to-worker-to-service configuration ownership | Complete | `40ade6c` |
| Phase 3.1 | Merge Subtitles workflow | Complete | `c2ed4d8` |
| Phase 3.2 | Add Chapters workflow | Complete | `0a7b49f` |
| Phase 3.3 | Blu-ray Remux workflow | Pending | — |
| Phase 3.4 | Blu-ray Encode workflow | Pending | — |
| Phase 3.5 | SP, track alignment, and missing-track repair | Pending | — |
| Phase 3.6 | Audio conversion and Dolby Vision | Pending | — |

## Phase 1 — Contract and Safety Baseline

Date: 2026-07-20  
Commit: `d889262` (`chore: establish phase 1 refactoring baseline`)

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
Commit: `40ade6c` (`refactor: unify GUI and runtime task configuration`)

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
Commit: `c2ed4d8` (`refactor: unify subtitle merge workflow`)

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
Commit: `0a7b49f` (`refactor: unify add chapters workflow`)

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
