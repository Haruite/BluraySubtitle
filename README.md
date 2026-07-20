# BluraySubtitle

[English](./README.md) | [简体中文](README.zh-Hans.md)

Development: [mandatory code modification standards](docs/development/code-standards.md) | [refactoring history](docs/refactoring/refactoring-history.md)

Windows x64 executable: [download](https://sbx.mysmy.top/tools/BluraySubtitle_windows_x64.exe)

BluraySubtitle is a GUI tool for Blu-ray workflows on **Windows / Linux** (including **Docker**).  
It brings the following five areas of functionality together in one application:

1. **Blu-ray Remux**
2. **Blu-ray Encode**
3. **Blu-ray DIY** (not yet implemented)
4. **Merge Subtitles**
5. **Add Chapters To MKV**

---

## Highlights

- One application covers the common full Blu-ray workflow (Remux, Encode, DIY, merge subtitles, chapters).
- Features are **auto-configured**—low learning curve; casual users can finish tasks with just a couple of clicks.
- The UI still offers **high freedom** for advanced users.
- **Careful operation logic** and **strong error recovery**.
- Cross-platform: **Windows / Linux / Docker**.

---

## More Details

### UI / Interaction

- **Language**: English / Simplified Chinese.
- **Themes**: Light / Dark / Colorful (with opacity).
- **Table-centered compact** workflow.
- Press the **bottom** button to start work; the UI **stays responsive** while jobs run.
- On-screen settings drive internal processing—**what you see is what you get**.
- If the current GUI state cannot produce a valid task configuration, the task does not start and reports an error; a previous configuration is never reused.

### Series / Movie Mode

- **Series mode** for per-episode splitting, or **Movie mode** without splitting.
- Built-in logic splits episodes along the **chapter timeline**; optional **approx. episode length** helps estimation.
- Per-row **start chapter / end chapter** (chapter span control in remux / encode flows).

#### Playlist management

- **Main MPLS** is chosen automatically with high accuracy.
- You can **pick the main MPLS manually**; each disc volume allows **any number** of main playlists.
- The main playlist supports **chapter-segment selection**, linked with **start / end chapter** splitting.
- **Unchecked** segments in the main MPLS plus **other playlists** are treated as **bonus SP** material.

### Track Management

- Every track **except video** can be selected independently.
- A built-in default track-selection policy adapts to different disc layouts—**not** “select everything”, but keeps what matters.
- **Select all tracks** in one click.

### Bonus SP Management

- Each **SP row** can be selected independently.
- SP rows that contain **useful** content are auto-selected.
- Multiple SP layouts are supported so valid disc extras are covered.

### Remux / Encode Controls

Encode mode supports two input sources:

- Blu-ray (original disc layout)
- Remux (MKV)

The **main playlist** supports editing the mux command (`remux_cmd`). Every selected main playlist must have exactly
one non-empty command line; a count mismatch is rejected before the task starts.

Encode options include:

- **`vspipe` source**: bundled / system
- **Encoder**: **x264 / x265 / SvtAv1EncApp**
- **Encoder binary source**: bundled / system
- **Output video bit depth**  
  - x264: 8 / 10 bit  
  - x265: 8 / 10 / 12 bit  
  - SvtAv1: 8 / 10 / 12? bit (see in-app notes)
- Encoder **presets** and **custom** parameters
- **Lossless audio recompression**: **FLAC / AAC / Opus**
- **Subtitle packaging**: external / softsub / hardsub
- **Per-row VPy path** for main episodes and SP rows
- **Remux-as-source** unlocks more actions, such as **editing chapters / attachments**.

### mkvtoolnix Compatibility Fixes

Built-in handling for common mkvtoolnix edge cases:

- Rewrite chapters when splitting/segmenting (where needed).
- When **MPLS direct mux fails**, automatic repair paths:
  - multi-clip **track-aligned concat** fallback,
  - **multi-episode split-output** fallback,
  - higher success rate on complex playlists.

### Implementation Notes (Plain Language)

This section explains, in plain language, how the program behaves internally.

#### A) SP handling rules

1. A **`select`** column decides whether an SP row participates in muxing.  
2. **No** branching by MPLS chapter count anymore: MPLS rows always use MPLS logic; if there is no MPLS, **M2TS** logic is used.  
3. **`table3` row order**: first by **BDMV volume** order, then by **MPLS name**, then rows **without MPLS** by **M2TS name**.  
4. Default SP output name is always **`BD_Vol_{bdmv_vol}_SP{n}.mkv`**; `n` is the 1-based index of **selected** MPLS rows on the same disc, zero-padded to a uniform width.  
5. If **every file** from an MPLS is already covered by the **main MPLS**, that row is added but **unchecked** by default.  
6. MPLS and M2TS shorter than **30 seconds** are still added to `table3` (duration uses **`get_duration_no_repeat`**; duplicate files counted once), but **unchecked** by default.  
7. **Special case**: if an MPLS includes **three or more distinct** files, it is **checked** by default.  
8. **Special case (single-frame still)**: MPLS has **one** m2ts and that m2ts has **only one frame** → checked by default, output **`BD_Vol_{bdmv_vol}_SP{n}.png`**.  
9. **Special case (multi still)**: MPLS has **multiple** m2ts and **each** has only one frame → checked by default, output is folder **`BD_Vol_{bdmv_vol}_SP{n}`**, files **`{m}-{m2ts_name}.png`** (`m` zero-padded from 1, `m2ts_name` without `.m2ts`).  
10. If **no track** is selected for an MPLS row, the output name is **empty** and the row is **skipped** at mux time.  
11. If **exactly one audio** track is selected, the output name uses the **original audio extension** and the track is **extracted** directly.  
12. If **multiple audio** tracks are selected (and there is no video mux path), output is **`BD_Vol_{bdmv_vol}_SP{n}.mka`**.  
13. **Subtitles**: one subtitle track → original extension; **multiple** subtitle tracks → **`.mks`**.  
14. After **track edits**, output filenames are **recalculated immediately**.  
15. After MPLS mux: clear chapters with **`mkvpropedit output.mkv --chapters ""`**, then build **`chapter.txt`** from MPLS, drop the **tail chapter marker**, and write chapters back **only** if the result is **not** “a single `00:00:00` chapter only”.  
16. If the **first m2ts** of an MPLS cannot be read, the row is **grayed out** (read-only) and **skipped** on mux.  
17. After mux completes, **track languages** are checked like main MPLS output; mismatches are fixed with **`mkvpropedit`**.  
18. Finally, scan **m2ts files not covered by any MPLS** and append them to `table3`:
    - classify with `M2TS.get_m2ts_type` / track composition: `video` / `audio_only` / `igs_menu` / `subtitle_only` / `audio_with_subtitle` / `private_or_other` / `mixed_non_video` / `unknown`;
    - the last three types are **unsupported** (grayed out: raw ES not identifiable after extract); **`igs_menu`** can be extracted but is **unchecked** by default;
    - duration via **`M2TS.get_duration`**;
    - duration **&lt; 30s** → unchecked by default;
    - duration **= 0** → grayed out, skipped;
    - when selected, base output name **`BD_Vol_{bdmv_vol}_{m2ts_name}`**;
    - suffix rules: one frame → **png**; single audio → **raw extract**; multi-audio → **mka**; single vs multiple subtitle and other cases → **mkv** (as per internal rules).

**When SP mux fails**

- Unreadable source (e.g. first m2ts missing) → row grayed out, skipped at run time.  
- Empty output name or no tracks selected → **intentional skip**, not an error.  
- MPLS rows: **primary mux first**; on multi-clip failure, **track-aligned concat fallback**.  
- Final success is judged by **whether the output file really exists** (including split-style suffix checks).  
- **Chapter rewrite** and **language fix** run only after **success**; failed rows stay failed but **do not block** other rows.

#### B) When MPLS mux fails — how it is repaired

`mkvmerge` can fail on MPLS mux (especially multi-file playlists) when m2ts layouts differ.  
The app checks return code and output validity; on failure it enters fallback repair.

**Single-output fallback** (common for SP, movie mode):

1. Take the tracks selected under **Edit tracks** in the GUI as the **reference layout**.  
2. Walk **`Chapter(mpls_path).in_out_time`**; for each clip compute:  
   - `start_time = (in_time * 2 - first_pts) / 90000`  
   - `end_time = start_time + (out_time - in_time) / 45000`  
   **Note:** `start_time` is **not** always “from file start”. Some playlists play the middle of file A, then file B, then return to A—not from time 0 of A.  
3. If `start_time == 0` and `abs(end_time - file_duration_sec) < 0.001`, mux the **whole** file; else use **`--split parts:start-end`**.  
4. Per clip, align to the reference layout:  
   - run **`mkvmerge --identify`**, then mux with **`mkvmerge`** using **only** the tracks that correspond to the selected PIDs;  
   - if tracks are still missing, probe with **tsMuxer**; if tsMuxer can supply **all** missing tracks **except audio**, **demux** those with tsMuxer and merge them in—otherwise **abort with an error**;  
   - any **audio** tracks still missing afterward are filled with **silence** tracks.  
5. Each clip mux command includes **`--track-order FID:TID,...`** so final track order matches the **first m2ts** reference.  
6. Concatenate clip outputs in order with **`+`** and **`--append-mode track`**.  
7. After mux, fix track languages with **`mkvpropedit`** where applicable.  
8. Write chapters (existing helpers); **audio compression** and later steps are handled elsewhere—this path covers mux and repair only.

**Multi-output fallback** (one MPLS → several files):

1. Derive per-output time windows from chapter config and/or **`remux_cmd`** split hints.  
2. Walk `in_out_time`, accumulate `((out_time - in_time) / 45000)` to place each m2ts on the playback timeline.  
3. If an m2ts interval **overlaps** the current output window, that m2ts participates in that output.  
4. Overlap slice bounds:  
   - **first** file in window: start = `window_start - clip_timeline_start`, end per single-output formula;  
   - **middle** files: same as single-output;  
   - **last** file in window: start per single-output, end = `start + (window_end - clip_timeline_start)`.  
5. Each slice: same **reference layout + missing-track repair + stable `--track-order`** (same rules as single-output fallback).  
6. Append slices into one file per window.  
7. Verify expected outputs (`-001`, `-002`, …) all exist; incomplete → fallback failed.  
8. On successful outputs: run the same **language fix** and **chapter write** pipeline as in the main flow.

#### C) `view chapters` / `start_at_chapter` / `end_at_chapter` linkage and config regeneration (refactor rules)

Config generation should treat at least these **three** inputs as core; **any** change triggers recompute:

1. MPLS segment check states in **`table1 → view chapters`**  
2. Per-row **`start_at_chapter`** in **`table2`**  
3. Per-row **`end_at_chapter`** in **`table2`**

**Priority 1: `view chapters` checkbox changes → full recompute**

1. First **checked** segment starts episode 1’s `start_at_chapter`.  
2. On an **unchecked** segment start, the current episode **ends** there; `end_at_chapter` is set; the next episode starts after that segment.  
3. Target length per episode: if subtitles exist, use subtitle **`max_end_time`**; else **`approx episode length`**.  
4. Two end candidates:  
   - **A**: nearest **file boundary** (from chapter view: this node vs previous node **changes m2ts**), and remaining time from this node to **end of MPLS** is **greater than** (estimated one-episode length **− 300 seconds**);  
   - **B**: nearest **chapter** node.  
5. Pick end:  
   - if A’s error is in **`[-¼ × target, +½ × target]`**, prefer **A**;  
   - else multiply **negative** error by **−2**, compare A vs B, take the smaller adjusted error as `end_at_chapter`.

**Priority 2: `start_at_chapter` changes → recompute from first changed episode**

1. Diff vs previous config; find the **earliest** episode whose start changed.  
2. Episodes **before** that stay unchanged.  
3. From the changed episode onward, recompute with the **same rules** (do not rely on old later starts).  
4. Sync uncheck: nodes between **previous episode end** and the **new start** are unchecked.

**Priority 3: `end_at_chapter` changes → expand / shrink**

1. Episodes before the changed one stay unchanged.  
2. If `end_at_chapter` is **moved earlier**: recompute **following** episodes.  
3. If `end_at_chapter` is **moved later**: next episode starts at the **first still-checked** node after the new end; recompute **following** episodes.

**Dropdown constraints**

- Nodes **unchecked** in `view chapters` must be **disabled** in both `start_at_chapter` and `end_at_chapter` combos.  
- Still require **`end_at_chapter > start_at_chapter`**.

#### D) Additional notes

- Main remux command placeholders: **`{output_file}`**, **`{audio_opts}`**, **`{sub_opts}`**, **`{parts_split}`**.  
- If the primary command output is wrong, fallbacks still use parsed args or default tracks where possible.  
- Chapter rewrite and language correction run **after mux** mainly to work around mkvtoolnix edge cases in metadata handling.

---

## Requirements

### Python packages

- `PyQt6`
- `librosa`
- `pycountry`

Example:

```bash
pip install PyQt6 librosa pycountry pillow matplotlib
```

### External tools

- mkvtoolnix: `mkvmerge`, `mkvinfo`, `mkvextract`, `mkvpropedit`
- `ffmpeg`, `ffprobe`
- `flac` (>= 1.5.0)

### Encode mode extras

- VapourSynth runtime + required plugins
- `vspipe`
- `vsedit`
- `x264`
- `x265`
- `SvtAv1EncApp`
- `fdkaac`

> Bundled vs system paths depend on the current mode and settings.

---

## Quick Start

```bash
python src/main.py
```

1. Pick language and theme at the top.  
2. Open the target **function** tab.  
3. Load source folder/file for the current mode.  
4. Confirm **main MPLS** and table mapping.  
5. Adjust tracks, chapter range, or encode options if needed.  
6. Click the bottom **Run** button to start the task.

---

## Usage by mode

## 1) Merge Subtitles

Typical flow:

1. Load Blu-ray folder.  
2. Load subtitle folder.  
3. Check paths / duration / chapter mapping.  
4. Reorder rows if needed.  
5. Run merge.

Tips:

- If mapping fails, check **main MPLS** first.  
- If subtitle order is wrong, **click the filename column header** to sort, or drag rows to reorder.  
- If a subtitle duration looks impossible, fix the subtitle file first (right-click **edit** prioritizes lines with the latest end times; fix ends or delete bad lines).
- Selected rows are read directly from the current table when the task starts; stale checkbox state is not reused.
- SRT, ASS, SSA, and SUP are supported. Subtitle formats cannot be mixed within one merged output.
- The suffix is applied exactly as displayed. Presets include the leading dot, such as `.en` and `.zh-Hans`.
- Each result is written beside the Blu-ray disc folder and beside its main playlist. If any planned output already exists, the task stops before writing and does not overwrite it.
- **Complete Blu-ray Folder** applies in both series and movie mode.

## 2) Add Chapters To MKV

Typical flow:

1. Load Blu-ray chapter source (playlist/chapter info).  
2. Load target MKV folder.  
3. Verify main MPLS.  
4. Run chapter write.

Behavior:

- MKVs are initially listed by filename. The task captures and uses their current visible table order when it starts.
- Selected main playlists are used in order, and MKVs are matched sequentially through their durations and playlist chapter marks. MKV filenames do not need a `BD_Vol_NNN` marker.
- **Edit Original File Directly** applies chapters with `mkvpropedit`. When it is unchecked, `mkvmerge` writes each result to an `output` subfolder of the source MKV directory.
- Every main playlist, MKV input, required MKVToolNix executable, and deterministic output collision is checked before the worker starts. Existing outputs are errors and are never overwritten.
- Chapter matching is planned before any MKV is changed. If the selected playlists cannot cover all listed MKVs, the task stops without writing chapters.

## 3) Blu-ray Remux

Typical flow:

1. Load Blu-ray folder.  
2. (Optional) Load subtitle folder.  
3. Verify main MPLS and chapter span.  
4. (Optional) Edit remux command.  
5. Choose output folder and run.

## 4) Blu-ray Encode

Typical flow:

1. Choose input source (**Blu-ray / Remux**).  
2. Configure VPy, encoder, subtitle packaging, etc.  
3. (Optional) Edit tracks / **select all tracks**.  
4. (Optional) Set **start / end chapter** per row.  
5. Run encode.

---

## VPy Editing and Preview

- **Edit script (`edit_vpy`)**: opened with the **system default editor** for the file type.  
- **Preview script (`preview_script`)**: opened with **`vsedit`**, with row-aware preview context.  
- Default script path: **`vpy.vpy`**.

---

## `setup_linux_environment.sh` (Linux runtime environment)

`setup_linux_environment.sh` builds the program’s Linux runtime environment. Currently supported:

- Ubuntu 22.04 / 24.04 / 25.10 / 26.04  
- Debian 12 / 13  

Prefer running `setup_linux_environment.sh` in a **remote terminal**: it uses **tmux** for cleaner, easier-to-read logs.

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

Apple Silicon (amd64 container):

```bash
docker build --platform linux/amd64 -t bluray-subtitle-ubuntu .
docker pull --platform linux/amd64 haruite/bluraysubtitle:latest
```

---

## Troubleshooting

- **Wrong episode mapping**  
  - Check **main MPLS**; play the MPLS and pick the correct one.  
  - Check chapter ends. 
  - Check subtitle row order (sort by filename column).  
  - Check subtitle duration; abnormally long files are often broken subtitles—use right-click **edit** / delete as needed.
- **Bonus / extra disc**  
  - Uncheck **main MPLS** for that bonus-disc volume.
- **Preview won’t start**  
  - Check **`vsedit`** path.  
  - Check VPy file and plugins.
- **Docker / Linux playback issues**  
  - Check `DISPLAY`, audio forwarding, and **mpv** availability.

---

## FAQ

### Does encode auto-crop black borders?

No—automation can’t cover all cases. Add crop logic in your VPy if you need it.

### How do I run a short encode test?

Add a trim before the final output in VPy, for example:

```python
res = res.std.Trim(first=0, length=720)
```

### Why is remux larger than the original disc?

Usually **duplicated bonus clips** across playlists. Check each MPLS and **View chapters**; if a playlist overlaps the main one, set that MPLS as **main MPLS**, open **View chapters**, uncheck overlapping segments, then **uncheck** the matching rows in the **SP** table below.

### Does encode tag chapters as OP/ED?

No. Remux the disc first, then in encode mode choose **Remux** as the source and use **Edit chapters** to set chapter titles.

### Why does getnative report different native resolutions per episode?

Normal: some discs mix resolutions and authoring is messy. Run a test pass; if results are similar, keep **auto getnative**. Otherwise disable it and edit the VPy with the resolution/scaling you trust—or leave those fields empty.

### Why does PotPlayer / mpv show two audio tracks on an MPLS (and eac3to / mkvmerge list two) while this app shows one?

One track is **hidden** by MPLS rules. Players and tools that read **m2ts** or **clpi** still list both. **PowerDVD** follows MPLS strictly—you won’t see the hidden track there.  
Usually the remaining audible material for that extra track appears elsewhere on the disc in another MPLS; **Blu-ray Remux** and **Encode** handle this so valid audio is not dropped.

### Why is the codebase so large?

The workflow is large, and much of the code was AI-generated with redundancy—I clean it when I notice it and when fixing bugs, and plan a broader refactor when time allows.

### Is the program reliable? Can AI-written code be trusted?

Use your own judgment.

---

## Credits

- [tsMuxer](https://github.com/justdan96/tsMuxer)
- [BluRay](https://github.com/lw/BluRay)
- [shinya](https://github.com/shimamura-hougetsu/shinya)
- [ass2bdnxml](https://github.com/Masaiki/ass2bdnxml)
- [BDSup2Sub](https://github.com/mjuhasz/BDSup2Sub)
- [Spp2Pgs](https://github.com/subelf/Spp2Pgs)
