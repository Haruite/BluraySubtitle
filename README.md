# BluraySubtitle

[English](./README.md) | [简体中文](./README_zh.md)

BluraySubtitle is a GUI tool for Blu-ray workflows on Windows/Linux (including Docker).  
It provides four integrated modes:

1. **Merge Subtitles**
2. **Add Chapters To MKV**
3. **Blu-ray Remux**
4. **Blu-ray Encode**

---

## Highlights

- End-to-end Blu-ray workflow in one app (merge, chapter, remux, encode).
- Reliable playlist/episode handling with **Series/Movie** modes.
- Strong remux resilience (automatic fallback and repair paths).
- Practical encode workflow with per-row vpy script editing/preview.
- Cross-platform support: Windows, Linux, Docker.

---

## More Details

### UI / Workflow Features

- **Language switch**: English / Simplified Chinese.
- **Theme switch**: Light / Dark / Colorful (with opacity control).
- Main playlist selection (`main MPLS`) per disc.
- Built-in playback actions (`play`) for fast verification.
- Compact table-first workflow with drag/drop where relevant.

### Track Management

- Per-source track editing dialog (audio/subtitle).
- **Select all tracks** one-click option (including remux-source workflows).
- Track selections are applied in remux/encode command generation.
- SP/main/remux contexts use dedicated keys so selections stay consistent.

### Remux / Encode Controls

- Support for both **Blu-ray source** and **Remux source** in encode mode.
- Editable remux command field (`remux_cmd`) for main playlist.
- Encode controls:
  - `vspipe` source (bundled/system),
  - `x265` source (bundled/system),
  - x265 profile/params,
  - subtitle packaging: external / softsub / hardsub.
- Per-row VPy path support for episodes and SP entries.

### Episode / Movie Logic

- **Series mode** and **Movie mode** switch behavior.
- Chapter-based episode splitting and timeline mapping.
- **Optional start chapter / end chapter** control in remux/encode tables.
- Chapter-segment outputs and SP handling in series workflows.

### mkvtoolnix Bug/Compatibility Workarounds

The project contains explicit repair logic for common mkvtoolnix edge cases:

- **Rewrite chapters** when needed for split/segment outputs.
- **Fix output track languages** with `mkvpropedit` post-process.
- **Auto-repair when MPLS mux fails**:
  - fallback remux paths for multi-clip playlists,
  - track-aligned concat strategy,
  - split-output fallback for multi-episode outputs.

These paths are used to improve output stability across inconsistent source playlists.

### Implementation Notes (Easy To Read)

This section explains the internal behavior in plain language.

#### A) SP remux rules 

1. Add a `select` column to decide whether the SP row should be remuxed.
2. Do not branch by MPLS chapter count anymore; MPLS rows always use MPLS logic, and if no MPLS is available then M2TS logic is used.
3. `table3` row order is: first by BDMV volume order, then by MPLS filename, and finally non-MPLS rows by M2TS filename.
4. Default SP output name is always `BD_Vol_{bdmv_vol}_SP{n}.mkv`; `n` is the index of selected MPLS rows inside the same disc, starting at 1 with zero-padding to equal width.
5. If all files from an MPLS are already covered by main MPLS, that SP row is added but unchecked by default.
6. MPLS and M2TS shorter than 30 seconds are still added to `table3` (duration uses `get_duration_no_repeat`, duplicate files counted once), but unchecked by default.
7. Special case: if an MPLS includes 3 or more distinct files, it is checked by default.
8. Special case 1: one-m2ts MPLS and that m2ts has only one frame -> checked by default, output becomes `BD_Vol_{bdmv_vol}_SP{n}.png`.
9. Special case 2: multi-m2ts MPLS and every m2ts has only one frame -> checked by default, output is folder `BD_Vol_{bdmv_vol}_SP{n}`, files are `{m}-{m2ts_name}.png` (zero-padded `m`, `m2ts_name` without `.m2ts`).
10. If no track is selected for an MPLS row, output name is empty and that row is skipped at remux time.
11. If exactly one audio track is selected, output name becomes the original raw extension and the track is extracted directly.
12. If multiple audio tracks are selected (and no video path is needed), output is `BD_Vol_{bdmv_vol}_SP{n}.mka`.
13. After track edits, output filename is recalculated immediately.
14. For MPLS remux output: clear chapters first (`mkvpropedit output.mkv --chapters ""`), then rebuild chapter text from MPLS, drop the tail chapter marker, and only write it back if it is not just a single `00:00:00` chapter.
15. If first m2ts cannot be read for an MPLS row, that row is grayed out (read-only) and skipped during remux.
16. After remux, check output track languages the same way as main MPLS output, and fix mismatches using `mkvpropedit`.
17. Final scan also adds leftover m2ts files not included in any MPLS:
    - duration from `M2TS.get_duration`,
    - `< 30s` -> unchecked by default,
    - `0s` -> grayed out and skipped,
    - selected output base name `BD_Vol_{bdmv_vol}_{m2ts_name}`,
    - extension rule: one-frame -> png, one audio -> raw extract, multi-audio -> mka, otherwise mkv.

SP failure handling:

- If a row is unreadable (for example first m2ts cannot be parsed), it is disabled in UI and skipped directly.
- If output name is empty or no track is selected, that row is treated as intentionally skipped (not an error).
- For MPLS rows, primary remux runs first; if it fails on multi-clip playlists, the app tries track-aligned concat fallback.
- After fallback, output is validated by actual file existence (including split-style suffix variants if produced).
- Chapter rewrite and language fix only run on successful outputs; failed rows are left as failed and do not block other rows from continuing.

#### B) What happens when MPLS remux fails

`mkvmerge` may fail on MPLS remux (especially split outputs) when m2ts files have different track layouts.
The app checks command result + output files; if invalid, it enters fallback repair.

Single-output fallback (common for SP and movie mode):

1. Analyze tracks from the first m2ts and treat it as the reference layout.
2. Iterate `Chapter(mpls_path).in_out_time` clip by clip:
   - `start_time = (in_time * 2 - first_pts) / 90000`
   - `end_time = start_time + (out_time - in_time) / 45000`
3. If `start_time == 0` and `abs(end_time - file_duration_sec) < 0.001`, do full-file mux; otherwise mux with `--split parts:start-end`.
4. For each clip's track layout:
   - tracks not in reference (hex PID not present in first clip) are dropped,
   - tracks present in reference are kept,
   - missing reference audio tracks are replaced with generated silence tracks.
5. Build per-clip mux command with aligned `--track-order FID:TID,...` so output track order always matches the first m2ts.
6. Append all per-clip mkv results in order with `+` and `--append-mode track`.
7. Run language fix with `mkvpropedit` (same path as main remux).
8. Write chapters (chapter generation/rewrite path); audio compression and other post steps are handled elsewhere.

Multi-output fallback (when one MPLS should produce multiple files):

1. Resolve output split windows from chapter config and/or parsed split hints in custom `remux_cmd`.
2. Walk `in_out_time`, accumulate clip playback time `((out_time - in_time) / 45000)` to get each clip timeline span.
3. For each target output window, include clips that overlap this time range.
4. Compute each included clip slice:
   - first clip in window: start is `window_start - clip_timeline_start`, end follows single-output formula,
   - middle clips: same formula as single-output path,
   - last clip in window: start follows single-output formula, end is `start + (window_end - clip_timeline_start)`.
5. Mux sliced pieces with the same reference-track alignment, missing-track silence fill, and stable `--track-order`.
6. Append pieces into one output per window.
7. Validate all expected outputs (`-001`, `-002`, ...) exist; otherwise mark fallback failed.
8. For successful outputs, apply language fix + chapter write using existing helper flow.

#### C) `view chapters` / `start_at_chapter` / `end_at_chapter` linkage and config regeneration rules

The config-generation function should use at least these 3 input groups, and any change in them must trigger regeneration:

1. MPLS segment check states from `table1 -> view chapters`
2. Per-row `start_at_chapter` values in `table2`
3. Per-row `end_at_chapter` values in `table2`

Priority order for change handling:

**Priority 1: view-chapters check-state changes (full recompute)**

1. First episode starts from the first checked segment.
2. If an unchecked segment start is encountered, current episode ends immediately there; next episode starts from the end of that segment.
3. Target episode length:
   - if subtitle timing exists: use subtitle `max_end_time`,
   - otherwise: use configured `approx episode length`.
4. For each episode, evaluate two end candidates:
   - Candidate A: nearest file-end node (node where m2ts changes vs previous node in chapter view),
   - Candidate B: nearest chapter node.
5. End-node selection:
   - if Candidate A deviation is within `[-1/4*target, +1/2*target]`, pick A first;
   - otherwise multiply negative deviation by `-2`, then compare A/B and pick the smaller adjusted deviation as `end_at_chapter`.

**Priority 2: `start_at_chapter` changes (recompute from first changed episode)**

1. Compare with previous config and find the earliest episode whose start changed.
2. Keep all episodes before that unchanged.
3. Recompute that episode and all following ones with the same rules above (ignore old later starts).
4. Uncheck nodes between previous episode end and the new start of the changed episode.

**Priority 3: `end_at_chapter` changes (expand/shrink branches)**

1. Episodes before the changed one stay unchanged.
2. If end is moved earlier: keep later episodes unchanged, and uncheck now-empty gap nodes.
3. If end is moved later: next episode starts from the first checked node after the new end, then recompute following episodes.

Disabled-option behavior:

- Nodes unchecked in `view chapters` must be disabled in both `start_at_chapter` and `end_at_chapter` dropdown options.
- Base constraint still applies: `end_at_chapter > start_at_chapter`.

#### D) Other useful internal behaviors

- Main remux command supports placeholders like `{output_file}`, `{audio_opts}`, `{sub_opts}`, `{parts_split}`.
- If primary command output is invalid, fallback still runs using parsed command info or default track selection.
- Chapter rewrite and language fix are post-remux steps to avoid mkvmerge metadata edge cases.

---

## Requirements

### Python packages

- `PyQt6`
- `librosa`
- `pycountry`

Install:

```bash
pip install PyQt6 librosa pycountry
```

### External tools

- mkvtoolnix: `mkvmerge`, `mkvinfo`, `mkvextract`, `mkvpropedit`
- `ffmpeg`, `ffprobe`
- `flac` (>= 1.5.0)

### Encode mode extras

- VapourSynth runtime + required plugins
- `vspipe`
- `x265`
- `vsedit`

> Depending on mode and platform, tools can come from bundled path or system path.

---

## Quick Start

```bash
python BluraySubtitle.py
```

1. Select language/theme.
2. Select mode tab.
3. Load source folders/files.
4. Confirm main playlist and table mapping.
5. Configure tracks/options if needed.
6. Run from the bottom action button.

---

## Mode Usage

## 1) Merge Subtitles

Typical:

1. Load Blu-ray folder.
2. Load subtitle folder.
3. Check mapping/duration/chapter alignment.
4. Adjust rows if needed.
5. Run merge.

Useful notes:

- If subtitle order is wrong, sort by path or drag rows.
- If alignment is wrong, verify main MPLS and chapter index mapping.

## 2) Add Chapters To MKV

Typical:

1. Load Blu-ray metadata source (playlist/chapter info).
2. Load MKV folder.
3. Verify main MPLS.
4. Run chapter injection.

## 3) Blu-ray Remux

Typical:

1. Load Blu-ray folder.
2. (Optional) load subtitle folder.
3. Verify main MPLS and chapter range mapping.
4. Edit remux command if needed.
5. Choose output folder and run.

## 4) Blu-ray Encode

Typical:

1. Choose source type (Blu-ray or Remux).
2. Configure VPy/x265/subtitle packaging options.
3. (Optional) edit tracks / select all tracks.
4. (Optional) set start/end chapter per row.
5. Run encode.

---

## VPy Editing and Preview

- **Edit script**: opened with **system-associated editor**.
- **Preview script**: opened with **vsedit** and uses runtime source/subtitle context for preview.
- Default script file: `vpy.vpy`.

---

## build.sh (Linux Runtime Environment Script)

`build.sh` is a script used to build the program runtime environment for specific Linux systems, currently supporting:
- Ubuntu 22.04 / 24.04 / 25.10 / 26.04 (beta)
- Debian 12 / 13

It is recommended to run `build.sh` in a remote terminal, because remote terminal execution uses tmux output and logs are cleaner and easier to read.

---

## Docker

Build image:

```bash
docker build -t bluray-subtitle-ubuntu .
```

Pull prebuilt:

```bash
docker pull haruite/bluraysubtitle:latest
```

Example run:

```bash
xhost +local:docker
sudo docker run -it --rm \
  --device /dev/snd \
  -e DISPLAY=$DISPLAY \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /path/to/media:/data \
  --ipc=host \
  --shm-size=2gb \
  bluray-subtitle-ubuntu
```

Apple Silicon (amd64 container) example:

```bash
docker build --platform linux/amd64 -t bluray-subtitle-ubuntu .
docker pull --platform linux/amd64 haruite/bluraysubtitle:latest
```

---

## Troubleshooting

- Wrong episode/subtitle mapping:
  - re-check main MPLS (play MPLS and choose the correct one),
  - verify chapter range; for example if the final chapter is copyright/notice content, trim it using one of these:
    - uncheck the last segment in `view chapters` of main playlist and save,
    - change the final episode `end_at_chapter` to the last real ending chapter,
    - edit remux command (`--split parts` / `--split chapters`) in mkvmerge docs: https://mkvtoolnix.download/doc/mkvmerge.html
  - reorder subtitle rows (you can sort by filename header),
  - verify subtitle durations; if a file is abnormally long, use right-click `edit` to fix or delete problematic subtitle lines.
- If there is a bonus/extra disc:
  - uncheck `main MPLS` for that bonus disc volume.
- Preview issues:
  - confirm `vsedit` path,
  - confirm VPy file exists and plugins are available.
- Playback issues in Docker/Linux:
  - verify DISPLAY/audio forwarding and mpv availability.

---

## FAQ

### Does encode mode auto-crop black borders?

No. Add crop logic in your VPy script if needed.

### How can I do a fast encode test?

Add a short trim before final output in VPy, for example:

```python
res = res.std.Trim(first=0, length=720)
```

Then remove it for full encode.

---
