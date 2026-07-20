# Phase 1 Refactoring Contract and Configuration Matrix

## Purpose

This document records the confirmed behavior contract for the Python refactor and maps the current GUI-to-execution configuration flow. It distinguishes current behavior from required behavior so that later refactoring does not silently invent business rules.

This is a refactoring baseline, not a claim that all listed target behavior is already implemented.

## Authority and Documentation Policy

- `README.md` and `README.zh-Hans.md` define the overall product behavior and are authoritative at that level.
- The implementation may contain necessary details that are not yet documented in the README files.
- An implementation detail may refine a README rule, but it must not contradict that rule.
- When a verified implementation detail is retained as intended behavior, both README versions must be updated together.
- When code behavior contradicts the README files, the contradiction must be reported and resolved explicitly. It must not be preserved merely for compatibility.
- Public facade and API compatibility is not a refactoring requirement. Compatibility wrappers may be removed when their removal simplifies the internal design and all in-repository callers are updated.

## Confirmed Product Contract

### GUI configuration is authoritative

- A value explicitly selected or entered in the GUI must be used by the task that is launched from that GUI state.
- Execution must not silently replace explicit GUI state with an older snapshot, an automatically generated default, or a module-level global value.
- Automatic inference is allowed only when the user has not supplied an explicit value.
- If an explicit configuration cannot be executed, the application must report an error instead of silently changing the configuration.
- Deterministic, actionable problems should be reported during configuration or launch preflight whenever practical. Execution-time failures that cannot be known in advance must still be surfaced clearly.
- Preflight must remain focused. The target is early feedback for known invalid state, not duplicated defensive validation in every layer.

### Output collisions

- An already existing planned output is an error.
- A task must not overwrite, skip, rename, or reuse an existing planned output implicitly.
- When all planned paths can be derived before launch, collision detection belongs in GUI/configuration preflight and must prevent the worker from starting.
- If a planned path can only be derived during execution, the first layer that derives it must fail explicitly before writing to it.

### Blu-ray DIY

- Blu-ray DIY remains visible and its code is retained.
- DIY execution is not implemented in this refactoring phase.
- Existing incomplete DIY execution behavior must not be presented as complete.
- Future DIY video encoding or conversion rules require a separate confirmed design.

### Track editing and conversion scope

- A configured track-language change must be applied by the execution pipeline.
- Video conversion is not a supported track-edit action for Blu-ray Remux or Blu-ray Encode.
- Blu-ray Encode encodes the main video through its encode workflow; this is not the same as a generic per-track video conversion setting.
- Possible DIY video encoding or conversion is deferred until DIY execution is designed.
- No new video-conversion behavior may be inferred for Remux, Encode, or DIY without confirmation.

### Testing cadence and media

- Changes are implemented in bounded phases.
- Each completed change must state whether business logic changed and identify the behavior affected.
- Tests are concentrated at the end of each phase, with targeted checks allowed during implementation when needed for safety.
- The user may add or perform material-based regression tests after receiving a precise checklist for the changed behavior.
- Large local media paths listed below are manual regression sources only. They are not CI fixtures, must not be assumed to exist on another machine, and must not be scanned or modified unless the relevant test is being performed.

## Current Configuration Flow

The current high-level flow is:

```text
GUI widgets and tables
    -> GUI-side dictionaries, lists, and snapshots
    -> RemuxWorker / EncodeWorker / EncodeMkvFolderWorker
    -> attributes on BluraySubtitle
    -> episodes_remux / episodes_encode / encode_task and related service methods
    -> generated external-tool commands and output files
```

The flow is not currently single-source. The same logical setting may be regenerated, restored from a snapshot, stored separately, or interpreted again by a service method.

### Primary flow matrix

| Concern | Current GUI or state source | Current worker transfer | Current service use | Known break or ambiguity | Required single-source target |
| --- | --- | --- | --- | --- | --- |
| Episode and chapter configuration | `table1`, `table2`, `_generate_configuration_from_ui_inputs()`, `_last_configuration_34`, and `_movie_configuration` | Passed as `configuration` to `RemuxWorker` or `EncodeWorker` | Assigned to `BluraySubtitle.configuration`, then passed again to `episodes_remux()` or `episodes_encode()` | Launch code can catch generation failure and use `_configuration_snapshot_for_service_run()`; movie mode uses a separate snapshot | Build one immutable launch request from current GUI state. Reject invalid current state; never substitute an old snapshot |
| Legacy global configuration | `src.core.settings.CONFIGURATION`; additional module-local assignments created with `global CONFIGURATION` | Not transferred as an explicit launch value | Some service modules import or fall back to `CONFIGURATION` | Imported and rebound globals can represent different objects and can override the explicit request path | Remove runtime dependence on global configuration. Every task receives its configuration explicitly |
| Selected main playlists | Current selection from `table1` through `get_selected_mpls_no_ext()` | `selected_mpls` | Used by Remux/Encode orchestration and fallback logic | Selection and configuration are collected separately and may become inconsistent after regeneration | Store selected playlists and their finalized rows together in the launch request and validate their relationship once |
| Main playlist chapter check state | Chapter/segment widgets associated with `table1` | Indirectly included through regenerated `configuration` and SP entries | Used to derive episode windows, main mux commands, and excluded SP material | Several refresh paths can regenerate data and restore old row values | Capture checked chapter segments once after the final GUI refresh; derive episode and SP plans from that same capture |
| `start_at_chapter` and `end_at_chapter` | Editable `table2` cells plus snapshot restoration | Inside `configuration` | Used for split bounds, chapter rewrite, and fallback output windows | Current UI generation may fail and fall back to earlier chapter bounds | Validate and capture current bounds; invalid ranges are configuration errors |
| Main `remux_cmd` | Editable command field in `table1`; applied later by `_apply_main_remux_cmds_to_configuration()` | Embedded as `main_remux_cmd` in configuration | `_make_main_mpls_remux_cmd()` uses configured templates or creates defaults | Applying commands is wrapped in a broad exception handler, so an edited command may be lost silently | Capture the current command with its playlist configuration. Parse/validate required placeholders before launch and fail visibly if invalid |
| Episode subtitle paths | `table2` cells | `sub_files` list | Used during subtitle generation and packaging | Collected independently from the episode configuration, so row order is the implicit join key | Store subtitle path and language on the same episode row object as its chapter window and output name |
| Episode subtitle language | `table2` language controls | `episode_subtitle_languages` list | Passed into Remux/Encode service flows | Parallel lists depend on stable row ordering | Store it on the corresponding episode row in the launch request |
| Episode output names | `table2` output-name cells and movie-generated names | `episode_output_names` list | Used for output planning and post-remux rename/finalization | Service code may also derive disc titles and names; existing files may be skipped in some downstream paths | Resolve every deterministic final path during preflight. The request contains the exact path, and any collision is an error |
| SP selection and output | `table3` check state and row fields | `sp_entries`; Encode also passes `sp_vpy_paths` | SP mux/extract/encode workflows | Entry construction has broad fallback rows; output naming can be recomputed by several refresh paths | Capture selected SP rows as complete records after final name recomputation; reject incomplete selected rows instead of fabricating placeholders |
| Per-row VPy path | Encode widgets in `table2` and `table3`, with a default VPy fallback | `vpy_paths` and `sp_vpy_paths`, or embedded in MKV-folder row dictionaries | `episodes_encode()` and `encode_task()` | Parallel arrays and exception fallbacks can detach a VPy path from its row | Store the effective VPy path on each encode row and validate it before launch |
| Encode input mode | `_encode_input_mode` and the Remux-folder path control | Selects either `EncodeWorker` or `EncodeMkvFolderWorker` | BDMV path uses `episodes_encode()`; Remux-folder path calls `encode_task()` per row | Two branches construct overlapping settings independently and do not share one request model | Use one encode request with an explicit input-source variant and shared encode options |
| Encoder, bit depth, binary source, and parameters | Encode controls and `_current_encode_tool_and_depth()` / `_effective_encode_params()` | Individual worker constructor arguments | Used by `episodes_encode()` or `encode_task()` | Values are loosely coupled arguments and some names remain x265-specific while other encoders are supported | Store normalized encode settings once; validate only encoder-specific constraints applicable to the chosen encoder |
| Subtitle packaging | Hard/soft/external radio buttons | `sub_pack_mode` | Used by encode task generation | Independently derived in both encode branches | Store one explicit enum-like value in the encode request |
| `getnative` | Encode checkbox | `use_getnative` | Assigned to `BluraySubtitle.use_getnative` | Separate attribute transfer makes omission easy | Store and pass it as part of the encode settings object |
| Copyright-tail trimming | GUI checkbox, limited to series Remux/Encode modes | `episode_trim_copyright_tail` | Worker registers selected MPLS paths before service execution | Registration is worker-side hidden state rather than part of an explicit episode plan | Precompute or explicitly describe the trim policy in the request; keep actual media-dependent calculation in the appropriate service boundary |
| Dolby Vision muxing | GUI checkbox | `mux_dolby_vision` | Constructor option on `BluraySubtitle`; encode also has a separate Dolby Vision preflight | Remux and encode handling is distributed across constructors and task helpers | Store the explicit policy in the request and run one mode-appropriate preflight |
| Track selection | `_track_selection_config`, keyed by source type/path | Passed to all three main workers | Read by Remux, fallback mapping, subtitle/chapter, and encode paths | Path-based keys and separate row structures can drift; behavior is spread across services | Attach selected track identities to the source row they belong to and translate them once at the service boundary |
| Track language edits | `_track_language_config` | Passed to workers and assigned to `BluraySubtitle.track_language_config` | No complete direct consumer chain was identified in the initial scan | GUI accepts the value, but execution cannot currently be proven to apply it | Apply every configured language change to the corresponding output track; add command-level and output-metadata verification |
| Track conversion edits | `_track_convert_config` | Not passed to Remux or Encode workers; currently consulted by limited GUI/encoder inference code | No general Remux/Encode service application path | A GUI-visible conversion choice is not an execution contract today | Do not add generic video conversion to Remux or Encode. Keep future DIY video conversion deferred; any supported non-video conversion must be represented explicitly and tested |
| Per-track lossless audio codec | `_track_lossless_audio_config` plus the default lossless codec control | Passed to all three main workers | Read by media/track mapping and encode/audio tasks | Separate maps and default normalization can conceal which choice wins | Resolve the effective codec per selected audio track in the launch request and retain one documented default rule |
| Output folder | GUI output-path control, sometimes transformed by `_resolve_remux_output_folder()` | Worker `output_folder` | Service code derives subdirectories and file paths | Final paths are not consistently known or checked before launch | Produce a complete planned-output set when possible; reject all existing paths before starting work |
| Existing outputs | Filesystem state checked in multiple workers/services | No unified transfer | Some paths skip existing files, some remove/replace temporary targets, and some infer success from file existence | This contradicts the confirmed collision contract and can make a new GUI configuration appear to succeed without running | A deterministic collision aborts preflight. A late-derived collision aborts before writing. No silent skip or overwrite |
| Merge Subtitles | Subtitle table and merge controls | `MergeWorker` builds/passes a configuration to subtitle generation | `generate_bluray_subtitle()` | Separate workflow with its own configuration construction; exact baseline tests are still required | Build one explicit merge request from current GUI state and validate required inputs once |
| Add Chapters to MKV | Chapter controls and selected MKV rows | Chapter configuration is passed to the relevant worker/service path | Chapter writing helpers | Chapter behavior shares helpers and legacy configuration concepts with Remux | Keep it an explicit independent request while reusing only the chapter-domain calculation and writing logic |
| Blu-ray DIY | Visible GUI and retained partial state/code | No confirmed complete execution request | Not implemented | Partial controls can suggest behavior that has no stable service contract | Retain the UI/code, label status accurately, and design the request only after DIY behavior is confirmed |

## Target Ownership Model

Later phases should converge on one launch object per workflow, with a shared structure where the workflows genuinely share concepts. The exact class names are intentionally not mandated by this document.

The ownership rules are:

1. GUI code reads widgets and tables once at launch.
2. GUI/configuration code normalizes explicit values, applies documented defaults only to unspecified values, and runs deterministic preflight.
3. A worker owns one complete request and does not read GUI widgets, global configuration, or GUI snapshots.
4. A service consumes plain Python data and does not reinterpret Qt tables.
5. Command builders receive the finalized values that they need. They do not silently invent replacements for invalid explicit values.
6. Output-path planning has one owner. Every downstream stage uses the planned paths.
7. Media-dependent fallback remains allowed only where the README defines it, such as MPLS mux repair. A fallback may change the technical method, but not the user's selected tracks, chapter ranges, names, languages, or other explicit output intent.

## Preflight Boundary

Preflight should cover information that is deterministic and useful before execution, including:

- required input and output locations;
- selected main playlist presence for BDMV Remux/Encode;
- valid chapter bounds and their relationship to the selected playlist;
- required per-row inputs for selected rows;
- valid explicit command templates and required placeholders;
- encoder/bit-depth combinations that are known to be unsupported;
- required tool availability for the selected workflow;
- every planned output collision that can be derived at launch.

Preflight should not duplicate deep media probing in multiple layers or reject valid inputs merely because an optional inference failed. Media-dependent problems discovered later must identify the affected row/source and fail explicitly unless a README-defined technical fallback can preserve the same requested result.

## Phase 1 Test Boundary

Phase 1 establishes the safety baseline. Its concentrated test pass should cover:

- Python syntax compilation and import smoke tests for supported entry modules;
- static enforcement that production code strings and comments follow the English-only rule, with user-facing English and Simplified Chinese mappings maintained in `I18N_ZH_TO_EN`;
- static consistency checks for `gui_base.py` and `service_base.py` against their split mixin implementations;
- characterization tests for configuration generation from representative series and movie GUI state;
- characterization tests for chapter-bound calculation, selected MPLS capture, SP row capture, track selection capture, output naming, and command-template propagation;
- launch-boundary tests that record exactly what each worker receives from a fixed GUI state;
- service-boundary tests that record the command inputs produced from a fixed request/configuration;
- regression tests demonstrating the current stale-snapshot/global-configuration and existing-output behaviors before those behaviors are intentionally changed in later phases;
- documentation parity review whenever retained implementation details are added to either README.

Tests that require external binaries or full media should be marked and separated from deterministic unit or characterization tests.

## Later Manual Media Regression Sources

These paths are local, user-provided sources for targeted manual regression. They are not CI requirements and their presence must be checked only when a relevant test is run.

| Source | Intended coverage |
| --- | --- |
| `E:\BDMV` | Anime Blu-ray samples; choose specific discs per changed series/movie, playlist, chapter, SP, track, or encode behavior |
| `E:\Movies\Avatar 2009 ULTRAHD BluRay 2160p HEVC Atmos TrueHD7.1-sGnb@CHDBits` | UHD movie mode and remux fallback behavior |
| `E:\Movies\疯狂动物城 Zootopia 2016 ULTRAHD BluRay 2160p HEVC Atmos TrueHD 7.1-sGnB@CHDBits` | UHD movie mode and remux fallback behavior |
| `E:\Movies\疯狂动物城2.Zootopia 2 2025 2160p UHD Blu-ray DoVi HDR10 HEVC TrueHD 7.1-x-man@HDSky` | UHD movie mode, Dolby Vision/HDR handling, and remux fallback behavior |

For each later phase, the handoff must name the smallest relevant subset of these checks, the expected outputs, and whether the test is read-only, writes temporary outputs, or invokes external tools.

## Required Change Reporting

At the end of every implementation batch, report:

- files changed;
- redundant or inconsistent paths removed;
- tests run and their result;
- tests still requiring user media;
- every business-logic change, including old behavior, new behavior, and the confirmed rule that authorizes it;
- any README detail that was added or synchronized.

If no business logic changed, state that explicitly.
