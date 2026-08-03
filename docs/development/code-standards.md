# Code Modification Standards

[简体中文](code-standards.zh-Hans.md)

## 1. Authority and Applicability

These standards are mandatory for every contributor submitting a pull request or code modification to this repository.

The authority order is:

1. this standards document;
2. the product behavior described by `README.md` and `README.zh-Hans.md`;
3. implementation details that do not conflict with the items above.

The implementation may contain more detail than the README, but it must not contradict the README. When verified product behavior is documented, both README versions must be synchronized.

When the author establishes a new rule, update this file and its Simplified Chinese counterpart before or in the same change as the code that relies on it. Every refactoring or major change must also update both [Refactoring History](../refactoring/refactoring-history.md) files. Ordinary changes do not require a history entry.

## 2. Simplicity and Consistency

- Use the simplest correct implementation.
- Remove duplicated, contradictory, unreachable, and unnecessary logic when it is within the current scope.
- Do not add speculative checks or abstractions for cases that the product does not require.
- Avoid any unnecessary validation unrelated to the objective. Prefer simple structural or literal checks, and use strict regular-expression matching only when the format itself is part of the requirement.
- Validate a fact at its owning boundary instead of repeating the same validation through every layer.
- Reuse one implementation for genuinely shared behavior. Do not force unrelated workflows through a shared abstraction merely because their code looks similar.
- Prefer one function for one complete operation. Do not split a straightforward operation into many tiny forwarding or one-line helpers.
- Keep the function count as low as practical without creating unrelated monolithic functions.
- Use names that describe the domain value or operation. Avoid meaningless temporary names except for conventional, tightly scoped indexes.
- Keep imports, type annotations, exception handling, and formatting consistent with the surrounding module.
- Do not retain compatibility wrappers or facade APIs unless an in-repository caller or a confirmed requirement needs them.
- Broad exception handlers must not hide invalid configuration or execution failure. They are acceptable only at a deliberate UI/worker boundary or best-effort cleanup boundary where the failure is still handled appropriately.

## 3. Source Language, Comments, and Names

- All Python source strings are English. The Chinese keys in `I18N_ZH_TO_EN` are the intentional catalog exception.
- All code comments and docstrings are English.
- Add comments for important domain rules, non-obvious calculations, ownership boundaries, and intentional exceptions.
- Do not add comments that only restate an obvious line of code.
- Use meaningful variable, function, class, and field names.

## 4. GUI Is the Execution Contract

- The current visible GUI state is authoritative: selected rows, order, paths, names, languages, modes, commands, chapter bounds, codecs, and other options must be applied exactly.
- Capture GUI state once at task launch and transfer it through one explicit request whenever practical.
- A worker or service must not silently replace an explicit GUI value with a stale snapshot, global value, default, regenerated value, or inferred alternative.
- Do not silently skip a selected GUI row or option. If the selected value cannot be executed, report an error.
- Automatic inference is allowed only when the user has not supplied an explicit value.
- Table order used by execution must match the visible order captured at launch unless the GUI explicitly documents another ordering rule.
- A worker owns the captured request. It must not read live GUI widgets after launch.
- Services consume plain Python data. They must not read or reinterpret Qt tables or widgets.
- Long-running work must run outside the GUI thread and keep progress, cancellation, success, and error behavior consistent.

## 5. Preflight and Failure Handling

- Check deterministic, actionable failures as early as practical, preferably before starting the worker.
- Preflight should focus on facts already known from the request: required paths, selected inputs, required tools, invalid ranges, incomplete row mappings, command structure, output paths, and deterministic collisions.
- Do not duplicate expensive media probing or add restrictive checks that reject valid inputs without a confirmed rule.
- Media-dependent failures discovered during execution must identify the affected source or row and fail clearly.
- An existing planned output is an error unless a confirmed product rule defines the workflow as resumable. Existing outputs must never be overwritten, renamed, or reused as a different result.
- A resumable workflow must document which output types count as completed and report every skipped output in task progress.
- When output paths can be derived before execution, derive and check the complete set before the first write.
- When mapping can be planned before execution, complete the plan before mutating source files or creating final outputs.
- External commands must have their return status checked. Tool-specific warning return codes may be accepted only when documented or verified.
- Prefer argument lists with `shell=False` for external tools. Use a shell only when shell syntax is genuinely required.
- Cleanup may remove only temporary or partial artifacts created by the current task. It must not delete a pre-existing user file.
- For a long-running Encode batch, deterministic request-wide safety failures must still stop before the worker starts. After row execution begins, a failure confined to one row must be recorded and must not prevent later rows from running. User cancellation and an unsafe request-wide state still stop the batch.
- Non-empty encoded elementary streams, partial containers, and extracted or injected dynamic-metadata artifacts created for a failed Encode row must be retained under unique non-final names and listed in the error report. They may be deleted only after that row's final output succeeds.
- Do not display a modal error dialog while a long-running Encode batch is active. Aggregate row warnings and failures, then present one summary after worker cleanup.

## 6. Layer Responsibilities

- GUI/configuration layer: read current controls once, normalize explicit values, perform deterministic preflight, and create the complete request.
- Worker layer: own one request, progress callback, cancellation state, and terminal success/error signaling.
- Service layer: execute workflow and domain logic from plain data without consulting GUI or hidden global state.
- Domain/tool layer: perform reusable media calculations and explicit external-tool operations.
- Avoid mutable module-level workflow configuration.
- Do not assign the same setting both as a service attribute and as a method argument.
- Share domain calculations and writing primitives; do not share stale workflow state.
- All methods implemented by mixins in `src/runtime/gui_runtime_split` must have matching declarations and signatures in `gui_base.py`.
- All methods implemented by mixins in `src/runtime/services_split` must have matching declarations and signatures in `service_base.py`.

## 7. i18n and User-Visible Text

- Every GUI string, dialog string, progress label, terminal message, and other user-visible output must have English and Simplified Chinese versions.
- English is the source string used by production code.
- Add the English mapping to `src/core/i18n.py:I18N_ZH_TO_EN` in the same change.
- Route user-visible text through `self.t(...)` or `translate_text(...)` at the appropriate presentation boundary.
- Dynamic messages should translate a stable template and then substitute values.
- Update `README.md` and `README.zh-Hans.md` together whenever product behavior or a user-relevant operational caution is documented.
- Except in dedicated implementation-notes or implementation-details paragraphs and sections, README files must not describe program implementation details. Keep them concise and include only current functionality, operational cautions, and other information useful to users. Historical comparisons, removed behavior, refactoring rationale, and future cleanup plans belong in refactoring history or development documents.

## 8. File Format

- Use UTF-8 for source and documentation files.
- Every new or modified non-`.sh` text file must use CRLF line endings.
- Shell scripts must use LF line endings so their shebang remains valid.
- Do not hard-wrap Markdown prose in the middle of a sentence. Keep a paragraph on one line when practical; if it is split, every resulting line must end at a complete sentence boundary. Preserve structural line breaks in lists, tables, code blocks, diagrams, and similar Markdown constructs; every list item must remain on its own line.
- Do not introduce trailing whitespace or malformed encoding.

## 9. Tool Versions and Dockerfile Maintenance

- Unless a confirmed compatibility or other technical constraint requires otherwise, dependencies and bundled tools must use the latest version published by the official upstream. Do not pin a version or commit without such a constraint.
- `Dockerfile` is the Ubuntu 26.04 adaptation of `setup_linux_environment.sh`. Do not add compatibility handling for other operating systems, explanatory output, or comments.
- Linux setup must place managed executables and VapourSynth plugins at the Linux paths defined by `src/core/settings.py`. Docker must install them directly at the corresponding Docker paths in that file, within each tool's existing build section; do not add a final relocation layer.
- Modify existing software in its corresponding Dockerfile build section even when the required change invalidates later layers. Do not put an unrelated small change near the beginning of the file; add genuinely new software near the end whenever practical so earlier layers remain cached.

## 10. Confirmed Product Constraints

Keep this section limited to confirmed product behavior that is easy to misunderstand or materially constrains future changes. Algorithm parameters, performance budgets, internal module or file ownership, and other implementation details belong in nearby code comments or refactoring history.

- The generated default VPy supports progressive sources only. Interlaced, telecined, or mixed-cadence material requires an explicitly suitable custom script.
- Remux-source Encode is resumable. Existing planned main, SP, external-subtitle, and companion outputs are treated as completed and skipped without overwrite; remaining rows continue. Duplicate paths within the current request remain errors.
- Blu-ray DIY remains visible and its code is retained. Its incomplete execution must not be presented as complete.
- Blu-ray Remux exposes a default-enabled option that converts selected lossless audio to FLAC. Disabled preserves source audio; Remux must not use AAC or Opus for this conversion.
- A successful DTS-family-to-FLAC conversion replaces the source only when the FLAC is no larger than the extracted DTS; otherwise the FLAC is discarded and the original DTS is retained. Successful PCM and TrueHD/MLP FLAC conversions are retained regardless of size.
- Final Remux and Encode outputs may automatically remove selected silent audio and exact decoded duplicates. Different known languages are never deduplicated, source order determines which duplicate is retained, and every removal is reported. This is an intentional exception to retaining every selected track.
- Blu-ray Encode staging Remux must preserve source audio. Encode audio conversion runs only in the final mux after video encoding succeeds.
- When Encode comparison images are enabled, each encoded video must save one source/encoded PNG pair selected by the same zero-based video frame number under `Compare` in the actual per-source output folder. Timestamp-based matching is not equivalent.
- Generic video conversion is not supported by Blu-ray Remux or Blu-ray Encode. Future DIY video conversion requires a separately confirmed design.
- Add Chapters matches current visible MKV order to selected main playlists sequentially and does not require `BD_Vol_NNN` in external MKV filenames.
- Application preferences use a versioned `config.json` beside the executable, or in the repository root for source runs. Frozen builds package `config.default.json` as the first-run template; the bundled `_MEIPASS` directory is never the writable configuration target.
- Update checks must be manual and asynchronous. They may query only the latest published full GitHub Release tag, compare its numeric version with the application-owned version, and must not download an update. A newer-version result must provide the GitHub Releases link and explicitly remind the user to copy `config.json` from the current program directory to the new program directory.
- Invalid application configuration must be reported and left untouched.
- Built-in Encode presets are read-only. Application configuration stores only user-defined presets, each owned by one encoder. The Encode page shows the built-in and user-defined presets for its current encoder, and directly editing the visible parameter field must not change the selected preset name.
- FDK-AAC and Opus bitrate value `0` means Auto rather than disabled or zero bitrate. Positive values are explicit kbps targets.
- The Advanced settings page must visibly warn that higher FFmpeg FLAC compression levels can significantly increase Remux time. It must also show stereo-music starting ranges of 128–256 kbps for FDK-AAC and 64–128 kbps for Opus, with Auto or a higher value recommended for multichannel or mixed channel layouts.
- Window geometry and current language, theme, font size, and opacity are saved automatically on a clean close. Restored geometry must not be replaced by first-run centering.

## 11. Testing and Change Reporting

- Add focused automated tests for every changed workflow boundary and every fixed regression that can be tested deterministically.
- For ordinary changes, run only the automated tests directly related to the modified behavior. Run the full repository test suite only for a major refactoring, a broad functional change, or when focused results reveal a credible wider regression risk.
- At minimum, run checks appropriate to the change from this set:
  - Python compilation and import smoke tests;
  - repository unit tests;
  - `tools/check_i18n.py`;
  - `tools/check_split_contracts.py`;
  - `git diff --check`;
  - CRLF/LF verification for new and modified files.
- Full Blu-ray and MKV media are manual regression inputs, not CI fixtures. Report exactly which real-media checks remain, what they write, and whether disposable copies are required.
- At the end of every modification batch, report:
  - files and areas changed;
  - redundant or conflicting paths removed;
  - every business-logic change, with old and new behavior;
  - tests run and results;
  - remaining manual media checks;
  - README, i18n, and standards updates, plus history updates when the change is a refactoring or major change.

## Modification Checklist

Before considering a change complete:

- [ ] Current GUI values reach runtime unchanged.
- [ ] No selected value is silently skipped or replaced.
- [ ] Deterministic failures and output collisions are checked early.
- [ ] Existing files cannot be overwritten implicitly.
- [ ] Code strings and comments are English.
- [ ] Every user-visible string has English/Simplified Chinese i18n.
- [ ] GUI/service split base declarations are synchronized.
- [ ] New and modified files have the required line endings.
- [ ] Tests appropriate to the change scope have been run; the full suite was reserved for a major or broad change unless wider risk required it.
- [ ] Both README versions are synchronized if behavior changed.
- [ ] Both standards files are updated if a new rule was confirmed.
- [ ] Both refactoring-history files are updated if the change is a refactoring or major change.
