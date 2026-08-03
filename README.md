# BluraySubtitle

[English](./README.md) | [简体中文](README.zh-Hans.md)

Documentation: [project wiki](docs/wiki/Home.md)

Development: [mandatory code modification standards](docs/development/code-standards.md) | [media pipeline and tool selection](docs/development/media-pipeline-and-tool-selection.md) | [refactoring history](docs/refactoring/refactoring-history.md)

The Windows x64 release is a one-folder package. Extract the complete archive, then run `BluraySubtitle_windows_x64.exe` without moving it away from the adjacent `_internal` directory. On first launch, the packaged `config.default.json` creates a writable `config.json` beside the executable. Source runs use the repository root instead. The program directory must therefore be writable; an invalid configuration is reported and left untouched.

Windows x64 downloads:

- [Continuously updated package](https://sbx.mysmy.top/tools/BluraySubtitle_windows_x64.7z): kept current independently of the GitHub release schedule.
- [GitHub Releases](https://github.com/Haruite/BluraySubtitle/releases): versioned packages published with each release.

BluraySubtitle is a GUI tool for Blu-ray workflows on **Windows / Linux** (including **Docker**). It brings the following five areas of functionality together in one application:

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

- **Language**: English / 简体中文 (native language names).
- **Themes**: Light / Dark / Colorful (with opacity).
- The top-right **Settings** dialog contains General, Paths, Advanced, External tools, and manual update options.
- Application settings and window size/position are remembered in `config.json`.
- **Table-centered compact** workflow.
- Press the **bottom** button to start work; the UI **stays responsive** while jobs run.
- On-screen settings drive internal processing—**what you see is what you get**.
- Tasks use the settings currently shown in the GUI. If those settings cannot form a valid task, the task does not start and reports an error.

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

The **main playlist** supports editing the mux command (`remux_cmd`). Each selected main playlist must have exactly one non-empty command and is processed in the current visible order, including multiple main playlists from the same disc. Before writing, Remux derives every command output and final episode filename. The output count must match the visible episode rows; duplicate paths and existing outputs are errors. Episode names are applied exactly as shown, and invalid filenames are rejected.

If the primary command and its documented fallback paths cannot create every planned output, Remux stops with an error and does not substitute unrelated files found in the output folder. After muxing, the language values saved by **Edit tracks** are applied to the included video, audio, and subtitle tracks and then verified. A mapping, tool, or verification failure stops that job and removes its newly created main outputs.

Remux keeps selected lossy audio unchanged. Its **Convert lossless audio to FLAC** option is enabled by default (the startup state is configurable under **Advanced**). All FLAC output prefers the standalone multithreaded `flac` encoder, which automatically uses the detected number of logical CPU threads, and falls back to `ffmpeg` if that encoder is unavailable or fails. Both FLAC encoders default to level 8 and can be configured independently on the **Advanced** settings page.
A DTS-family track is replaced only when its FLAC output is no larger than the extracted DTS; otherwise the original DTS track is retained. Successful PCM and TrueHD/MLP conversions remain FLAC even when the FLAC is larger. TrueHD Atmos is converted only after `truehdd` successfully decodes presentation 2. MKVToolNix does not repair damaged TrueHD frames. Affected DIY discs may produce many `truehdd` errors and a decoded FLAC track that is shorter than the video even when the MKV duration looks plausible; compare decoded audio/video durations before discarding the source track.
See [Media Pipeline Design and Tool Selection](docs/development/media-pipeline-and-tool-selection.md) for details.

With **Mux Dolby Vision** enabled, Remux combines compatible base and enhancement layers as profile 8.1; when it is disabled, the enhancement layer is not included.

Selected audio is also checked automatically even when **Convert lossless audio to FLAC** is disabled. A track whose decoded maximum volume is below -60 dB is removed as silent. Decoded fingerprints are compared only for tracks in the same source codec family with the same channel count; tracks with different known languages are kept, and an exact duplicate keeps the earliest track in source order.

Encode options include:

- **`vspipe` source**: bundled / system
- **Encoder**: **x264 / x265 / SvtAv1EncApp**
- **Encoder binary source**: bundled / system
- **Output video bit depth**
  - x264: 8 / 10 bit
  - x265: 8 / 10 / 12 bit
  - SvtAv1: 8 / 10 bit for normal output; the exposed 12-bit path is experimental and the setup-script build does not produce valid video
- Read-only built-in encoder presets, user-defined presets, and direct per-task parameter editing
- **Lossless audio recompression**: **FLAC / AAC / Opus**
- The startup encoder, bit depth, and preset come from **Advanced** settings. User-defined presets can be added, renamed, edited, and deleted there for the currently selected encoder, while built-in presets remain read-only. After startup, the visible Encode preset and parameter controls remain authoritative for every task.
- The startup lossless-audio target, subtitle packaging mode, getnative, automatic-crop, and output-comparison checkboxes also come from **Advanced** settings and remain freely editable before launch.
- The VPy row below those options exposes denoise, dehalo, dering, deband, and anti-aliasing strengths for the generated default script. `0` disables an individual stage; defect-specific dehalo and dering start disabled, while deband and anti-aliasing use a moderate `0.5` blend by default. All values can also be changed under **Advanced** settings.
- Automatic getnative can take substantial time and memory because it analyzes multiple frames and kernels. The common false-positive band from 535p through 545p is excluded, so genuinely native 540p material must be configured manually in the VPy.
- With **Auto-crop black borders** enabled, Encode analyzes multiple time points and applies one conservative fixed crop. Pixels used by any sampled active picture are preserved when borders vary over time.
- With **Output comparison images** enabled, every encoded video saves source and encoded PNGs from the same frame under **`<selected output>/<source folder name>/Compare`**.
- Lossless PCM, TrueHD/MLP, DTS-family, and FLAC tracks use the per-track FLAC/AAC/Opus choice shown in **Edit tracks**. Lossy audio is kept unchanged. TrueHD Atmos is converted only after `truehdd` successfully decodes presentation 2; if `truehdd` is unavailable or fails, the original TrueHD track is kept. Other selected conversion failures stop the row. When FLAC is selected, the same DTS/FLAC size rule described above applies. For Remux input, a missing tool required by an actual conversion is reported before launch.
  Final Encode muxing applies the same automatic silent/duplicate cleanup; Blu-ray staging Remux does not process audio.
- **Subtitle packaging**: external / softsub / hardsub
- **Per-row VPy path** for main episodes and SP rows
- **Remux-as-source** unlocks more actions, such as **editing chapters / attachments**.

### Managed x264 and x265 versions

The setup scripts and Docker image resolve the current official upstream source when they run or build:

- **[x264](https://code.videolan.org/videolan/x264)** uses the latest official `master` revision, built as one 8/10-bit-capable CLI. The Windows setup uses the MSYS2 UCRT64 toolchain and profile-guided optimization.
- **[x265](https://github.com/Multicorewareinc/x265)** uses the latest official stable numeric release tag, built as one statically linked 8/10/12-bit multilib CLI whose three linked cores enable native HDR10+ JSON input (`--dhdr10-info`) and Dolby Vision RPU input (`--dolby-vision-profile`, `--dolby-vision-rpu`).

The managed paths are defined in [settings.py](src/core/settings.py). To use another build, replace the corresponding executable at the same path.

The setup scripts also install the latest official [hdr10plus_tool](https://github.com/quietvoid/hdr10plus_tool) release.

For custom x265 builds, use the official multilib steps in `setup_windows_environment.ps1` or `setup_linux_environment.sh` as references.

Encode follows the visible row order and applies the displayed output names, per-row VPy scripts, subtitles, languages, track choices, and encoder settings. For Blu-ray input, its temporary Remux preserves the selected source audio; lossless-audio conversion runs only during the final mux after video encoding succeeds.

Encode automatically carries compatible source color and HDR metadata into the output, including HDR10+ for x265 10/12-bit output. Dolby Vision from a selected Blu-ray or Remux source is preserved as profile 8.1 with x265 10/12-bit output. x264 and x265 8-bit output cannot preserve Dolby Vision, while SVT-AV1 omits it with an explicit notice. When automatic cropping changes the encoded dimensions, Dolby Vision active-area metadata is adjusted for both native x265 writing and fallback post-injection.

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

1. The **`select`** column decides whether an SP row participates in muxing. The task waits for the SP scan to finish, then captures the visible row order, source, output name, selected tracks, and edited languages together.
2. MPLS rows always use MPLS logic; **M2TS** logic is used only when a row has no MPLS.
3. SP rows are ordered by **BDMV volume**, then **MPLS name**, followed by uncovered **M2TS names**.
4. The default MPLS output name is **`BD_Vol_{bdmv_vol}_SP{n}.mkv`**. The number is based on selected MPLS rows on the same disc and uses a consistent zero-padded width.
5. An MPLS already covered completely by the main MPLS is shown but unchecked by default.
6. MPLS and M2TS shorter than **30 seconds** remain visible but are unchecked by default. An MPLS containing at least three distinct files is checked by default.
7. A single-frame SP is written as PNG. Multiple single-frame files are written to a folder as **`{n}-{m2ts_name}.png`**.
8. No selected audio or subtitle track leaves the output name empty and intentionally skips that row. A single audio or subtitle track uses its elementary-stream extension; multiple audio tracks use `.mka`, multiple subtitle tracks use `.mks`, and normal video/container output uses `.mkv`.
9. Editing tracks recalculates the output name immediately. The runtime uses the exact visible output name and does not silently rename it or rediscover another file.
10. MPLS container outputs receive the MPLS chapters after muxing; a single zero-time chapter is omitted.
11. Unreadable or unsupported rows are disabled during scanning. If a selected source or its captured track configuration becomes unavailable, the task reports an error instead of silently skipping it.
12. Languages saved in **Edit Tracks** are applied and verified for `.mkv`, `.mka`, and `.mks` SP outputs, including tracks appended to an episode output. Raw streams and images cannot store this metadata, so such a language configuration is rejected before execution.
13. M2TS files not covered by any MPLS are also listed. Video, audio-only, IGS menu, subtitle-only, and audio-with-subtitle layouts are supported where a deterministic output can be produced; unsupported or zero-duration rows are disabled.

**When SP mux fails**

- Empty output names remain an intentional skip. Every selected row with a non-empty output is required to finish successfully.
- Sources, captured tracks, exact output paths, collisions, existing files, and required language tools are checked before output creation whenever they can be determined in advance.
- MPLS rows try the direct mux first, then use the same track-aligned fallback for one or multiple clips.
- An SP track appended to an episode must expose a valid `stream_id` or `original_transport_stream_id`; `properties.number` is not a transport PID, so a selected track with neither PID field fails.
- Success requires the exact planned output to exist. A failed selected row stops the task and removes only its task-created partial output; an episode file is replaced only after its SP mux has completed and been verified.

#### B) How track alignment and missing-track repair work

Direct MPLS muxing can fail when playlist clips have different track layouts. The fallback uses the tracks selected in **Edit Tracks** as the reference layout and processes every playlist clip against that layout:

1. Playback ranges come from `Chapter(mpls_path).in_out_time`; partial clips use `--split parts:start-end`.
2. `mkvmerge --identify` maps only the tracks visible and selected in **Edit Tracks**. Tracks hidden by the MPLS are excluded, and recovered tracks keep the GUI selection order.
3. Missing non-audio tracks are recovered with tsMuxer. If tsMuxer cannot supply all of them, the fallback fails explicitly.
4. Missing audio is also recovered with tsMuxer when possible. Only audio still unavailable afterward is replaced with matching-duration PCM silence using the reference sample rate, channel count, and bit depth.
5. The repaired PID set must exactly match the reference layout. One repaired clip is moved directly to the planned output; multiple clips are concatenated with `--append-mode file` so every track uses the same preceding-file timestamp boundary.
6. Main and standalone SP outputs then receive their configured track languages and chapters, with command results and final metadata checked.

The separate multi-output fallback used when one main MPLS is split into several episode files keeps the same per-clip alignment and missing-track rules, then validates every expected split output before finalization.

#### C) `view chapters` / `start_at_chapter` / `end_at_chapter` linkage and configuration recalculation

Episode configuration is recalculated when any of these **three** inputs changes:

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
- If the primary command output is wrong, fallbacks use parsed arguments and preserve explicit track choices; default tracks are used only when no explicit choice exists.
- After fallback, every planned output must exist; incomplete main-playlist output fails the task.
- Chapter rewrite and language correction run **after mux** mainly to work around mkvtoolnix edge cases in metadata handling.

---

## Requirements

### Python packages

- `PyQt6`
- `numpy`
- `soundfile`
- `pycountry`
- `Pillow` (imported as `PIL`)
- `matplotlib`

Example:

```bash
pip install PyQt6 numpy soundfile pycountry pillow matplotlib
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
- `hdr10plus_tool`
- `SvtAv1EncApp`
- `fdkaac`

> Bundled vs system paths depend on the current mode and settings. The External Tools path check probes the configured x265 executable. It requires `hdr10plus_tool` only when x265 advertises `--dhdr10-info`, and requires `dovi_tool` only when x265 advertises both Dolby Vision input options.

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
- Only rows selected in the current table when the task starts participate in the merge.
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

- MKVs are initially listed by filename and receive chapters in their current visible table order when the task starts.
- Selected main playlists are used in order, and MKVs are matched sequentially through their durations and playlist chapter marks. MKV filenames do not need a `BD_Vol_NNN` marker.
- **Edit Original File Directly** applies chapters with `mkvpropedit`. When it is unchecked, `mkvmerge` writes each result to an `output` subfolder of the source MKV directory.
- Every main playlist, MKV input, required MKVToolNix executable, and deterministic output collision is checked before writing. Existing outputs are errors and are never overwritten.
- Chapter matching is planned before any MKV is changed. If the selected playlists cannot cover all listed MKVs, the task stops without writing chapters.

## 3) Blu-ray Remux

Typical flow:

1. Load Blu-ray folder.
2. (Optional) Load subtitle folder.
3. Verify main MPLS and chapter span.
4. (Optional) Edit remux command.
5. Choose output folder and run.

Remux uses the currently displayed playlist order, commands, chapter ranges, output names, subtitle languages, track settings, Dolby Vision option, and **Complete Blu-ray Folder** setting. All main outputs are planned before writing; existing or duplicate outputs stop the task without overwrite or automatic renaming.

## 4) Blu-ray Encode

Typical flow:

1. Choose input source (**Blu-ray / Remux**).
2. Configure VPy, encoder, subtitle packaging, etc.
3. (Optional) Edit tracks / **select all tracks**.
4. (Optional) Set **start / end chapter** per row.
5. Run encode.

Encode uses the current row order, output names, VPy scripts, subtitles, languages, track choices, per-track audio conversion choices, and encoder settings. Planned outputs are never overwritten. Blu-ray input rejects existing outputs. Remux input reports and skips existing non-empty main/SP files, external subtitles, and companion files, then continues with the remaining work. Empty main/SP files and paths of the wrong type are rejected instead of treated as checkpoints.

---

## VPy Editing and Preview

- **Edit script (`edit_vpy`)**: opened with the **system default editor** for the file type.
- **Preview script (`preview_script`)**: opened with **`vsedit`**, with row-aware preview context.
- Default script path: **`vpy.vpy`**.
- The generated default script intentionally does not auto-process interlaced video because true interlace, telecine, and mixed cadence require different treatment; use a custom VPy as described in the [Encode/VapourSynth Wiki](docs/wiki/Video-Encoding-and-VapourSynth.md#interlaced-telecined-and-mixed-cadence-sources).

---

## Repository helper scripts

- [`src/scripts/batch_remux_movie.py`](src/scripts/batch_remux_movie.py): edit its paths or pass them on the command line to batch-remux every BDMV under one movie folder.
- [`src/scripts/getnative_file.py`](src/scripts/getnative_file.py): edit `video_file` and run it directly to print one video's automatic getnative result and elapsed seconds.

---

## `setup_windows_environment.ps1` (Windows environment setup)

`setup_windows_environment.ps1` configures the complete local runtime and build environment for **x64 Windows client and Windows Server systems**.

Before the first run, allow locally created PowerShell scripts for the current user, then start the setup from the repository root:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\setup_windows_environment.ps1
```

The script requests administrator permission, asks for the display language, and can be rerun after interruption. Downloads use the configured **Windows system proxy** automatically; configure the system proxy first when direct access to the download sources is unavailable.

---

## `setup_linux_environment.sh` (Linux runtime environment)

`setup_linux_environment.sh` builds the program’s Linux runtime environment. Only **x64** systems are supported. Current distributions:

- Ubuntu 22.04 or later
- Debian 12 or later

Make the script executable before the first run, then start it from the repository root:

```bash
chmod +x setup_linux_environment.sh
./setup_linux_environment.sh
```

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

Yes, as an opt-in Encode setting. It analyzes multiple time points without writing screenshots and uses a conservative fixed crop that is safe for all sampled active areas. This handles many constant or changing-border sources, but dark scenes, credits, overlays, and unusual mastering can still produce a wrong result. Always verify the reported margins and the encoded picture; leave the option disabled and use an explicit VPy crop when exact control is required.

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
- [getnative](https://github.com/Infiziert90/getnative)
- [my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script)
