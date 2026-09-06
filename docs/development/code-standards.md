# Code Modification Standards

English | [简体中文](code-standards.zh-Hans.md)

## 1. Authority and Applicability

These standards are mandatory for all repository changes. Resolve conflicts between repository documents and code in this order:

1. these standards;
2. product behavior described by `README.md` and `README.zh-Hans.md`;
3. implementation details.

Explicit requirements for a particular file or workflow take precedence over the corresponding general rules; product exceptions are collected in section 10.

Keep both language versions of these standards synchronized, and record author-confirmed rules before or with code that relies on them. When documenting confirmed product behavior or operational cautions, update both README versions. For refactoring or major changes, also update the [English](../refactoring/refactoring-history.md) and [Simplified Chinese](../refactoring/refactoring-history.zh-Hans.md) histories; ordinary changes need no history entry. Refactoring history records only actual changes and necessary verification results, excluding unchanged areas and discussions that led to no changes; it is not a source of current requirements.

## 2. Simplicity and Consistency

- Use the simplest correct implementation; remove duplicated, contradictory, unreachable, or unnecessary logic within the change's scope.
- Add validation or abstractions only when needed for the change's confirmed requirements. Prefer structural or literal checks; use strict regular-expression matching only when the format itself is required.
- Validate each fact at the boundary responsible for accepting it. Repeat a check only when its inputs or relevant external state may have changed.
- Share one implementation of common behavior; similar-looking code alone does not justify coupling unrelated workflows.
- Prefer one function per cohesive operation. Avoid trivial forwarding helpers or arbitrary splits, and do not merge unrelated responsibilities just to reduce the function count.
- Keep imports, type annotations, exception handling, and formatting consistent with the surrounding module.
- Retain compatibility wrappers or facade APIs only for in-repository callers or confirmed requirements.
- Catch broad exceptions only at deliberate GUI/worker or best-effort cleanup boundaries. Handle the failure explicitly without hiding invalid configuration or failed execution.

## 3. Source Language, Comments, and Names

- Python string literals and all code comments and docstrings must use English; the Chinese keys in the `I18N_ZH_TO_EN` translation catalog are the explicit exception.
- Explain important domain rules, non-obvious calculations, ownership boundaries, and intentional exceptions in comments; omit comments that only restate obvious code.
- Name variables, functions, classes, and fields for the domain values or operations they represent. Conventional short indexes are acceptable in a tight scope.

## 4. GUI Is the Execution Contract

- Subject to the exceptions in section 10, execution must apply the visible GUI values captured at launch: selected rows, paths, names, languages, modes, commands, chapter bounds, codecs, and other options.
- Use the captured visible table order unless the GUI explicitly documents another ordering rule.
- Do not silently skip a selection or replace an explicit value with stale state, a global value, a default, a regenerated value, or an inference. Report an error if a selected row or option cannot execute. Infer values only when the user has not supplied them.
- Run long tasks outside the GUI thread, with consistent progress, cancellation, success, and error handling.

## 5. Preflight and Failure Handling

- Before starting a worker or writing outputs, check the request's paths, selections, required tools, ranges, mappings, command structure, and complete output plan for deterministic errors and collisions. Do not repeat expensive media probing or add restrictions without a confirmed rule.
- Media-dependent failures discovered during execution must identify the affected source or row and fail clearly.
- Existing planned outputs are collisions unless a confirmed resumable workflow documents them as completed outputs. Report each permitted skip. Do not overwrite, rename, or reuse a colliding output, or change the planned path to bypass the collision.
- Check every external command's exit status. Prefer argument lists with `shell=False`; use a shell only when its syntax is required. Accept warning exit codes only when their meaning is documented or verified for that tool.
- Cleanup may remove only temporary or partial artifacts created by the current task, never pre-existing files. Preserve non-empty artifacts from a failed Encode row under unique non-final names, list them in the error report, and delete them only after that row's final output succeeds.
- In an Encode batch, request-wide safety failures, cancellation, and unsafe state stop the batch; an isolated row failure is recorded and later rows continue. Present one summary after worker cleanup instead of modal errors during the batch.

## 6. Layer Responsibilities

- GUI/configuration: read current controls once at launch, normalize their representation without changing their meaning, perform deterministic preflight, and create a complete request. Use one explicit request object whenever practical.
- Worker: own the captured request, progress callback, cancellation state, and final success/error signaling. Do not read live GUI widgets after launch.
- Service: execute workflow and domain logic from plain Python data, without reading or reinterpreting Qt tables/widgets or consulting hidden global state.
- Domain/tool: perform reusable media calculations and explicit external-tool operations.
- Avoid mutable module-level workflow configuration. Share domain calculations and writing primitives without sharing stale workflow state.
- Do not supply the same setting through both a service attribute and a method argument.
- Mixin methods in `src/runtime/gui_runtime_split` and `src/runtime/services_split` must have declarations with matching signatures in `gui_base.py` and `service_base.py`, respectively.

## 7. i18n and User Documentation

- Application-authored user-visible text, including GUI labels, dialogs, progress, and terminal messages, must support English and Simplified Chinese. Add or update entries in `src/core/i18n.py:I18N_ZH_TO_EN` in the same change: Chinese text is the key, and its English source string is the value.
- Translate at the presentation boundary through `self.t(...)` or `translate_text(...)`. For dynamic text, translate a stable template before substituting values.
- Keep README content focused on current functionality, operational cautions, and other information useful to users. Confine implementation details to dedicated implementation-notes or implementation-details paragraphs/sections. Put historical comparisons, removed behavior, and refactoring rationale in refactoring history; put future cleanup plans in development documents.

## 8. File Format

- Use UTF-8 for source and documentation. New or modified text files must use CRLF, except shell scripts and Dockerfiles (`Dockerfile` and `*.dockerfile`), which require LF to preserve shebang and shell-heredoc behavior.
- Keep Markdown paragraphs on one line when practical; split prose only at complete sentence boundaries. Preserve structural line breaks in lists, tables, code blocks, diagrams, and similar constructs, with each list item on its own line.
- Do not introduce trailing whitespace or malformed encoding.

## 9. Tool Versions and Dockerfile Maintenance

- The supported operating systems and architectures are exactly those accepted by `setup_windows_environment.ps1` and `setup_linux_environment.sh`: currently x64 Windows 10 or later, Windows Server 2019 or later with Desktop Experience, Ubuntu 22.04 or later, and Debian 12 or later. Check changes against that whole range, not just the development machine; do not add compatibility branches for other systems. Evaluate Linux features in the repository's Docker environment as well; do not present a feature as supported in Docker if it cannot run there.
- Use the latest version published by the official upstream for dependencies and bundled tools. Pin a version or commit only for a confirmed compatibility or other technical constraint.
- Setup scripts and the Dockerfile must install every executable, library, and plugin used by their respective runtime. Source builds must explicitly enable every optional feature the application uses.
- `Dockerfile` adapts `setup_linux_environment.sh` to Ubuntu 26.04. In the Dockerfile, do not add compatibility handling for other operating systems, explanatory output, or comments.
- Linux setup must install managed executables and VapourSynth plugins at the Linux paths defined by `src/core/settings.py`. Docker must install them directly at that file's corresponding Docker paths within each tool's build section; do not add a final relocation layer.
- Modify existing software in its corresponding Dockerfile build section even if later layers lose their cache. Do not put unrelated changes near the beginning; add new software near the end when dependencies permit, to preserve earlier cached layers.

## 10. Confirmed Product Constraints

Keep this section limited to confirmed exceptions and product semantics that would otherwise be ambiguous. Implementation details belong in nearby code comments or refactoring history.

- **ISO subtitle merging:** ISO input is limited to reading BDMV playlists for subtitle merging, not preview, Remux, or Encode. Release image access as soon as the playlists have been read; do not keep images mounted for the task.
- **Main-playlist Remux selection:** **Edit Tracks** controls video, audio, and subtitle selection. The editable mux command uses `{video_opts}`, `{audio_opts}`, and `{sub_opts}` placeholders; manually entered track-selection flags are ignored and replaced at execution from the captured track selection.
- **Automatic getnative:** When the actual source height exceeds 1080 pixels, Encode reports a skip and omits automatic getnative even if selected. Higher-resolution analysis requires manually running `src/scripts/getnative_file.py` and configuring the VPy.
- **Resumable Encode:** Remux-source Encode skips completed main, SP, external-subtitle, and companion outputs without overwriting them, then continues the remaining work. Main/SP file outputs must be non-empty; directory-source rows require the expected directory output. Empty main/SP files or paths of the wrong type are errors. Existing external-subtitle and companion files count as completed. Duplicate paths within the current request remain errors.
- **Blu-ray DIY:** Keep the feature visible and retain its code; do not present incomplete execution as complete.
- **Automatic audio removal:** Final Remux and Encode outputs may remove selected silent audio and exact decoded duplicates, with every removal reported.
- **MPLS logical tracks:** At load time, build track choices only from the complete playlist's STN. Within one MPLS, the STN category and ordinal stream number identify a logical track across PlayItems; PID changes and partial presence do not create separate logical tracks. **Edit Tracks** shows one row per logical track, all its distinct PIDs, and a concise status with a per-PlayItem timeline in the tooltip. Language changes are informational; keep the first explicit non-`und` language as the default.
- **Missing track occurrences:** An STN-declared occurrence missing from its M2TS PAT/PMT fails the output by default. The disabled-by-default partial-missing policy may turn an audio or subtitle occurrence into a timeline gap only when PAT/PMT confirms its absence, tsMuxer cannot provide it, and the same logical track exists elsewhere in the output. A selected track absent from the entire output, any missing video occurrence, or any transport-format conflict must fail visibly.
- **Transport compatibility:** Limit MPLS and M2TS PAT/PMT checks to parameters those structures expose. Do not add speculative full-payload parsing or normalization for Matroska append incompatibilities, such as payload-only PCM bit-depth/channel-layout or codec-private changes, until the author confirms a policy. If MKVToolNix encounters such a change, fail explicitly; do not synthesize replacement packets, silently discard another track, or promote a partial file to final output.
- **Cross-MPLS identity:** Compare tracks by their sets of `(absolute M2TS path, PID)` pairs. Persist selection identity with the source MPLS and its STN category/slot; never deduplicate providers by PID or slot alone.
- **Audio conversion:** FLAC, AAC, and Opus conversion must preserve a logical track's leading and intermediate timeline gaps without synthesizing silence. Process and validate its continuous PCM intervals as one transaction; failure in any interval keeps the complete original track. Duration-loss fallback excludes authored gaps and uses the largest positive shortening of any one interval, never the sum of interval losses.
- **Audio-gap sidecars:** After audio-gap analysis, Remux must persist one sidecar per output, recording gap-bearing tracks or a valid empty marker when all audio is continuous. Remux-source Encode must prefer a valid matching sidecar, including an empty marker; otherwise, detect the actual packet timeline during the single source-audio decode. Missing metadata does not establish continuity.
- **Bitrate:** FDK-AAC and Opus bitrate `0` means Auto; positive values are explicit kbps targets.
- **Series-mode SP matching:** Compare complete M2TS detail: clip names, order, and time ranges. First, a non-main MPLS matching exactly one complete selected main MPLS contributes track choices to that shared main remux. Otherwise, an SP matching exactly one episode is appended only after splitting. A partial match spanning several episodes remains an ordinary SP. Movie mode uses neither attachment path.
- **SP default selection:** For a complete-main match, aggregate tracks without overlapping physical M2TS/PID relations, sort by representative PID, and apply the common default-selection algorithm once. For a single-episode match, apply that algorithm independently to the main and SP MPLS, then deduplicate physical relations again when attaching.

## 11. Testing and Change Reporting

- Do not add or modify test files for a bug fix unless it is both major and important. When a major feature or a refactoring warrants test changes, focus on critical, error-prone behavior.
- Keep the suite small: retain tests for critical calculations, track/timeline identity, output safety, and consequential failure handling. Do not cover every feature detail or add tests that merely check source strings, GUI layout, default values, or internal call forwarding. Assert behavior and results; consolidate repeated scenarios and remove unused fixtures.
- Mocked tool results verify application decisions, not media correctness. Audio/video synchronization, stream integrity, and actual encoder/muxer behavior require representative real-media checks.
- For ordinary changes, run only tests directly related to the changed behavior. Run the full suite only for a major refactoring, a broad functional change, or when focused results reveal a credible wider regression risk.
- For every change, run `git diff --check` and verify text-file encoding and line endings. Select other checks by scope: Python compilation/import smoke tests, relevant unit tests, `tools/check_i18n.py` for source-language/i18n changes, and `tools/check_split_contracts.py` for mixin/base changes.
- Full Blu-ray and MKV media are manual regression inputs, not CI fixtures. For any remaining real-media checks, specify what must be checked, what will be written, and whether disposable copies are required.
- At the end of each change batch, report changed files/areas, removed redundancy or conflicts, each business-logic change as before/after behavior, checks and results, remaining manual media checks, and applicable README, i18n, standards, and history updates.
