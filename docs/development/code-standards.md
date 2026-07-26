# Code Modification Standards

[简体中文](code-standards.zh-Hans.md)

## 1. Authority and Applicability

These standards are mandatory for every contributor submitting a pull request or code modification to this repository.

The authority order is:

1. this standards document;
2. the product behavior described by `README.md` and `README.zh-Hans.md`;
3. implementation details that do not conflict with the items above.

The implementation may contain more detail than the README, but it must not contradict the README. When verified implementation behavior is retained, both README versions must be synchronized.

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
- Update `README.md` and `README.zh-Hans.md` together whenever product behavior or retained implementation detail is documented.
- README files describe current functionality, retained implementation behavior, and operational cautions. Historical comparisons, removed behavior, refactoring rationale, and future cleanup plans belong in refactoring history or development documents, not in README.

## 8. File Format

- Use UTF-8 for source and documentation files.
- Every new or modified non-`.sh` text file must use CRLF line endings.
- Shell scripts must use LF line endings so their shebang remains valid.
- Do not introduce trailing whitespace or malformed encoding.

## 9. Confirmed Product Constraints

- Remux-source Encode is resumable. Existing planned main, SP, external-subtitle, and companion outputs are treated as completed and skipped without overwrite; remaining rows continue. Duplicate paths within the current request remain errors.
- Blu-ray DIY remains visible and its code is retained. Its incomplete execution must not be presented as complete.
- Configured track-language changes must be applied to the output.
- Blu-ray Remux exposes a default-enabled option that converts selected lossless audio to FLAC after main and SP muxing. Disabled preserves source audio; Remux must not use AAC or Opus for this conversion.
- FLAC output must prefer the configured standalone `flac` encoder and automatically use the detected number of logical CPU threads. Compressed lossless sources may be decoded to PCM by `ffmpeg` first; an unavailable or failed standalone encoder falls back to `ffmpeg` for FLAC encoding. Standalone and FFmpeg FLAC compression levels default to 8 and may be configured independently; FFmpeg output for actual audio decoding or encoding remains visible.
- A successful DTS-family-to-FLAC conversion replaces the source only when the FLAC is no larger than the extracted DTS; otherwise the FLAC is discarded and the original DTS is retained. Successful PCM and TrueHD/MLP FLAC conversions are retained regardless of size.
- Final Remux and Encode outputs automatically remove selected audio whose decoded maximum volume is below -60 dB and exact decoded duplicates within the same source codec family and channel count. Different known languages are never deduplicated, the earliest source-order track is retained, and every removal is reported. This documented cleanup is an intentional exception to retaining every selected track.
- Automatic final-audio cleanup must extract all selected audio tracks in one `mkvextract` invocation and reuse those extracted files for analysis and conversion. It must not reopen a large source Matroska once per selected audio track.
- Blu-ray Encode staging Remux must preserve source audio. Encode audio conversion runs only in the final mux after video encoding succeeds.
- Generic video conversion is not supported by Blu-ray Remux or Blu-ray Encode. Future DIY video conversion requires a separately confirmed design.
- Every selected main MPLS corresponds to exactly one non-empty main Remux command.
- README-documented technical fallback may change the method used, but it must preserve explicit GUI intent such as selected tracks, languages, chapter ranges, names, and output paths.
- Add Chapters matches current visible MKV order to selected main playlists sequentially and does not require `BD_Vol_NNN` in external MKV filenames.
- Application preferences use a versioned `config.json` beside the executable, or in the repository root for source runs. Frozen builds package `config.default.json` as the first-run template; the bundled `_MEIPASS` directory is never the writable configuration target.
- Update checks must be manual and asynchronous. They may query only the latest published full GitHub Release tag, compare its numeric version with the application-owned version, and must not download an update. A newer-version result must provide the GitHub Releases link and explicitly remind the user to copy `config.json` from the current program directory to the new program directory.
- Invalid application configuration must be reported and left untouched. Configuration writes must replace the complete file atomically.
- The External Tools settings page edits the effective `src/core/settings.py` source, validates Python syntax before atomic replacement, and applies changes on the next launch. Frozen builds must seed an editable source copy outside `_MEIPASS`. The page must check currently active configured tool paths, list missing tools, and direct users to the platform setup script in the repository root.
- Startup page, default Series/Movie mode, and configured Remux/Encode output folders provide initial GUI values only. Page-specific edits must be retained during the current session, and task execution must continue to capture the current visible output folder rather than rereading the configuration file.
- Default Encode encoder, bit depth, preset, preset parameters, lossless-audio target, subtitle packaging, and getnative state initialize the visible Encode controls at startup only. The configured Remux lossless-to-FLAC default likewise initializes its visible checkbox. Launched tasks must continue to capture those visible controls. Audio compression levels and bitrates must be captured into each immutable Remux/Encode request before worker launch; workers must not reread live GUI or configuration state.
- FDK-AAC and Opus bitrate value `0` means automatic behavior: FDK-AAC uses VBR mode 5, while Opus uses 128 kbps for up to two channels and 256 kbps for more channels. Positive values are explicit kbps targets.
- The Advanced settings page must visibly warn that higher FFmpeg FLAC compression levels can significantly increase Remux time. It must also show stereo-music starting ranges of 128–256 kbps for FDK-AAC and 64–128 kbps for Opus, with Auto or a higher value recommended for multichannel or mixed channel layouts.
- Window geometry and current language, theme, font size, and opacity are saved automatically on a clean close. Restored geometry must not be replaced by first-run centering.

## 10. Testing and Change Reporting

- Add focused automated tests for every changed workflow boundary and every fixed regression that can be tested deterministically.
- Run the concentrated repository test suite when a workflow or phase is completed.
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
- [ ] Focused and concentrated tests have been run as appropriate.
- [ ] Both README versions are synchronized if behavior changed.
- [ ] Both standards files are updated if a new rule was confirmed.
- [ ] Both refactoring-history files are updated if the change is a refactoring or major change.
