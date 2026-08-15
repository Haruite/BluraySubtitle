# Code Modification Standards

English | [简体中文](code-standards.zh-Hans.md)

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
- Intentional exception: Encode skips automatic getnative with user-visible progress when the actual source height exceeds 1080p, even if the GUI option is selected. Higher-resolution getnative remains a manual `src/scripts/getnative_file.py` and VPy configuration workflow.
- Automatic inference is allowed only when the user has not supplied an explicit value.
- Table order used by execution must match the visible order captured at launch unless the GUI explicitly documents another ordering rule.
- A worker owns the captured request. It must not read live GUI widgets after launch.
- Services consume plain Python data. They must not read or reinterpret Qt tables or widgets.
- Long-running work must run outside the GUI thread and keep progress, cancellation, success, and error behavior consistent.

## 5. Preflight and Failure Handling

- Before starting a worker or writing output, check only deterministic, actionable facts already known from the request: paths, selections, required tools, ranges, mappings, command structure, and the complete planned output set and its collisions. Do not repeat expensive media probing or add restrictions without a confirmed rule.
- Media-dependent failures discovered during execution must identify the affected source or row and fail clearly.
- An existing planned output is an error unless a confirmed resumable workflow defines it as completed; never overwrite, rename, or reuse it. Such workflows must document completed output types and report each skip.
- Check every external command's return status. Prefer argument lists with `shell=False`; use a shell only when its syntax is required. Accept warning return codes only when documented or verified.
- Cleanup may remove only temporary or partial artifacts created by the current task, never pre-existing files. Preserve non-empty artifacts from a failed Encode row under unique non-final names, list them in the error report, and delete them only after that row's final output succeeds.
- In a long-running Encode batch, request-wide safety failures, cancellation, and unsafe state stop the batch; an isolated row failure is recorded and later rows continue. Present one summary after worker cleanup instead of modal errors during the batch.

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
- Every new or modified text file other than shell scripts and Dockerfiles must use CRLF line endings.
- Shell scripts must use LF line endings so their shebang remains valid.
- Dockerfiles (`Dockerfile` and `*.dockerfile`) must use LF line endings so shell heredocs do not pass carriage returns to commands.
- Do not hard-wrap Markdown prose in the middle of a sentence. Keep a paragraph on one line when practical; if it is split, every resulting line must end at a complete sentence boundary. Preserve structural line breaks in lists, tables, code blocks, diagrams, and similar Markdown constructs; every list item must remain on its own line.
- Do not introduce trailing whitespace or malformed encoding.

## 9. Tool Versions and Dockerfile Maintenance

- Unless a confirmed compatibility or other technical constraint requires otherwise, dependencies and bundled tools must use the latest version published by the official upstream. Do not pin a version or commit without such a constraint.
- The setup script and Dockerfile must install every executable, library, and plugin used by their runtime. Source builds must explicitly enable every optional feature the application uses.
- `Dockerfile` is the Ubuntu 26.04 adaptation of `setup_linux_environment.sh`. Do not add compatibility handling for other operating systems, explanatory output, or comments.
- Linux setup must place managed executables and VapourSynth plugins at the Linux paths defined by `src/core/settings.py`. Docker must install them directly at the corresponding Docker paths in that file, within each tool's existing build section; do not add a final relocation layer.
- Modify existing software in its corresponding Dockerfile build section even when the required change invalidates later layers. Do not put an unrelated small change near the beginning of the file; add genuinely new software near the end whenever practical so earlier layers remain cached.

## 10. Confirmed Product Constraints

Keep this section limited to confirmed exceptions to the general rules above and product semantics that would otherwise be easy to misinterpret. Implementation details belong in nearby code comments or refactoring history.

- Remux-source Encode is resumable. Existing planned main, SP, external-subtitle, and companion outputs are treated as completed and skipped without overwrite; remaining rows continue. Duplicate paths within the current request remain errors.
- Blu-ray DIY remains visible and its code is retained. Its incomplete execution must not be presented as complete.
- Final Remux and Encode outputs may automatically remove selected silent audio and exact decoded duplicates, with every removal reported. This is an intentional exception to retaining every selected track.
- FDK-AAC and Opus bitrate value `0` means Auto rather than disabled or zero bitrate. Positive values are explicit kbps targets.
- Series-mode SP handling has two independent exact-detail rules: a non-main MPLS matching one complete selected main MPLS contributes track choices to that shared main remux, while a non-whole SP matching one unique episode is appended only after splitting. A partial match spanning several episodes remains an ordinary SP. Movie mode uses neither attachment path.

## 11. Testing and Change Reporting

- Do not add or modify test files for a bug fix unless the fix is both major and important. When test changes are warranted for a major feature or refactoring, keep them focused on critical, error-prone behavior.
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
