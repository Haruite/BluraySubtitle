# BluraySubtitle

English | [简体中文](README.zh-Hans.md)

Documentation: [project wiki](docs/wiki/Home.md) | [interface guide and examples](docs/wiki/Interface-Guide.md)

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

## Features and controls

### Interface and task settings

- English/Simplified Chinese UI; Light, Dark, and Colorful themes with opacity control.
- **Settings** contains General, Paths, Advanced, External tools, and manual update options. Settings and window geometry are saved in `config.json`.
- Series mode splits along the chapter timeline; movie mode keeps one continuous output. Each disc can have multiple selected main MPLS files. Automatic selections and episode estimates need review. See [chapter-range recalculation](docs/wiki/BluraySubtitle-Developer-Guide.md#episode-configuration) for how segment and chapter edits interact.
- Tasks use the visible row order, names, ranges, commands, tracks, and languages captured at launch. Invalid settings are reported before execution. See the [interface examples](docs/wiki/Interface-Guide.md) for selection and review.

### Remux controls

Each selected main MPLS has one non-empty editable mux command. Planned outputs must match the visible episode-row count; invalid filenames are rejected. **Edit Tracks** controls video, audio, and subtitle choices; manual track-selection flags in the command are replaced by those choices. Logical-track rows show PIDs and status, with per-PlayItem details in the tooltip; incompatible tracks are disabled.

- **Allow partially missing non-video tracks** is disabled by default. It permits physically absent audio/subtitle intervals only when tsMuxer cannot recover them and the track exists elsewhere in the output. Missing video or a whole missing selected track still fails.
- **Trim copyright bumper** can remove complete trailing clips in an episode's final 30 seconds when the episode ends at the M2TS file end. Review the result; see the [exact rule and exceptions](docs/wiki/Blu-ray-Disc-Structure.md#short-copyright-bumpers-at-the-end).
- Selected external subtitles are soft-muxed into the main MKV. Remux does not burn them into video or copy them as external outputs.
- **Mux Dolby Vision** converts compatible layers to profile 8.1; disabling it excludes the enhancement layer. See [profile 8.1 limitations](docs/wiki/Media-Formats-and-Dolby-Vision.md#profile-81-in-this-project).

Saved track languages are applied and verified after muxing. Mapping/tool/language failures stop the task and remove its newly created main output. Track-count and MKVToolNix packet-statistics checks instead produce a final warning summary while later Remux work continues.

### Audio controls

- Remux does not re-encode lossy tracks. **Convert lossless audio to FLAC** starts enabled; its startup state and the standalone/FFmpeg FLAC levels (both default to 8) are configurable under **Advanced**.
- **Convert DTS:X and TrueHD Atmos to FLAC during Remux** is separate and starts disabled because FLAC cannot retain object metadata.
- Final Matroska audio cleanup runs even when FLAC conversion is off: it removes tracks below `-60 dB` decoded maximum volume and exact decoded duplicates within the same codec family and channel count. Different known languages are kept; duplicates retain the earliest source track. Every removal is reported. Standalone single-track audio skips this cleanup.
- Conversion preserves authored gaps in Matroska without adding silence; sparse standalone audio is rejected. Keep the adjacent `.audio-gaps.json` sidecar for later Remux-source Encode, including its valid empty marker for continuous audio.
- A failed conversion keeps the original track. The greatest continuous-interval shortening is reported above 0.1 seconds; loss above the configurable threshold (default 1 second) discards the conversion.

See [audio formats and conversion targets](docs/wiki/Media-Formats-and-Dolby-Vision.md#lossless-audio-conversion-decisions) for format choices, and [media processing](docs/development/media-pipeline-and-tool-selection.md) for validation and recovery details.

### Encode controls

- Choose bundled/system `vspipe` and encoder binaries: x264 supports 8/10-bit, x265 8/10/12-bit, and SVT-AV1 normal output 8/10-bit. The exposed SVT-AV1 12-bit path is experimental and the setup-script build produces invalid video.
- Built-in presets are read-only. **Advanced** manages user presets and startup defaults; the visible parameter field controls each task.
- Each main/SP row has its own VPy path and per-track FLAC/AAC/Opus choices. Subtitle modes are external, softsub, and hardsub; Remux-source input also supports chapter/attachment editing.
- The generated VPy exposes denoise, dehalo, dering, deband, and anti-aliasing strengths. Startup defaults for these controls and the getnative/crop/comparison/frame-check options are stored under **Advanced**.
- Automatic getnative can use substantial time and memory and skips sources taller than 1080 pixels. Higher-resolution analysis uses `src/scripts/getnative_file.py` manually.
- Automatic crop is opt-in and needs visual review. Comparison images go to `<selected output>/<source folder name>/Compare`; full-frame PSNR reports go to `FrameCheck`. The full check rerenders the VPy and may take several times the video's duration.
- Compatible color/HDR metadata is carried forward. Dolby Vision preservation requires x265 10/12-bit; x264 and x265 8-bit cannot preserve it, while SVT-AV1 reports its omission. x265 10/12-bit also supports HDR10+; automatic crop adjusts Dolby Vision active-area metadata.

For defaults, parameters, preview keys, and metadata limitations, see [Video Encoding and VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.md).

### SP management

Review the SP table after main-playlist and episode selection. Rows can represent other playlists, excluded main intervals, or uncovered M2TS content. Track edits update the output name and format; matching commentary may share a main output or be appended to one episode. The [SP selection, naming, and attachment rules](docs/wiki/Blu-ray-Disc-Structure.md#main-content-and-sp-in-this-project) cover defaults and special discs.

### Managed x264 and x265 versions

The setup scripts and Docker image resolve the current official upstream source when they run or build:

- **[x264](https://code.videolan.org/videolan/x264)** uses the latest official `master` revision, built as one 8/10-bit-capable CLI. The Windows setup uses the MSYS2 UCRT64 toolchain and profile-guided optimization.
- **[x265](https://github.com/Multicorewareinc/x265)** uses the latest official stable numeric release tag, built as one statically linked 8/10/12-bit multilib CLI whose three linked cores enable native HDR10+ JSON input (`--dhdr10-info`) and Dolby Vision RPU input (`--dolby-vision-profile`, `--dolby-vision-rpu`).

The managed paths are defined in [settings.py](src/core/settings.py). To use another build, replace the corresponding executable at the same path.

The setup scripts also install the latest official [hdr10plus_tool](https://github.com/quietvoid/hdr10plus_tool) release.

For custom x265 builds, use the official multilib steps in `setup_windows_environment.ps1` or `setup_linux_environment.sh` as references.

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
- 7-Zip for reading playlists from ISO images

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

Notes:

- In **Merge Subtitles**, loading a folder also reads BDMV playlists from `.iso` files larger than 5 GiB, including uppercase extensions. This works on the supported Windows/Linux systems and in Docker without mounting images. Playlists are stored privately until the window closes; merged subtitles are written beside the ISO using its stem. ISO input does not provide preview, Remux, Encode, or disc-folder completion.
- If mapping fails, check **main MPLS** first.
- If subtitle order is wrong, **click the filename column header** to sort, or drag rows to reorder.
- If a subtitle duration looks impossible, fix the subtitle file first (right-click **edit** prioritizes lines with the latest end times; fix ends or delete bad lines).
- Only rows selected in the current table when the task starts participate in the merge.
- SRT, ASS, SSA, and SUP are supported. Subtitle formats cannot be mixed within one merged output.
- The suffix is applied exactly as displayed. Presets include the leading dot, such as `.en` and `.zh-Hans`.
- Each result is written beside the Blu-ray disc folder and beside its main playlist. If any planned output already exists, the task stops before writing and does not overwrite it.
- Multiple main playlists selected from one disc are merged independently. Their disc-folder-adjacent files append the MPLS stem to avoid filename collisions.
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
- The generated default VPy exposes the processed `res` as output index `0` and the original `src8` as output index `1`. See the [Encode/VapourSynth Wiki](docs/wiki/Video-Encoding-and-VapourSynth.md#previewing-processed-and-source-frames-in-vsedit) for VSEdit preview and snapshot hotkeys. This live preview is separate from the PNG files generated by **Output comparison images** after encoding.
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

PulseAudio or PipeWire-Pulse run example (recommended for most Linux desktops and remote desktop sessions):

```bash
xhost +local:docker
sudo docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  -e BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=pulse \
  -e PULSE_SERVER=unix:/tmp/pulse/native \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /run/user/$(id -u)/pulse/native:/tmp/pulse/native \
  -v bluray-subtitle-config:/config \
  -v /path/to/media:/data \
  --ipc=host \
  --shm-size=2gb \
  bluray-subtitle-ubuntu
```

The named `bluray-subtitle-config` volume stores `config.json` and the generated `vpy.vpy`. Reuse the same volume name on later runs so settings changed in the application are loaded even when the container uses `--rm`.

The container runs desktop applications as the non-root user `ubuntu` with UID/GID `1000`; mounted media must be accessible to that user.

Choose exactly one of these Docker audio methods:

- **PulseAudio or PipeWire-Pulse (recommended):** use the three `BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=pulse`, `PULSE_SERVER`, and `/pulse/native` options in the complete example above.
- **Native PipeWire without PipeWire-Pulse:** replace those three Pulse options with:

  ```bash
  -e BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=pipewire \
  -v /run/user/$(id -u)/pipewire-0:/tmp/runtime-ubuntu/pipewire-0
  ```

- **ALSA-only host:** replace the three Pulse options with the following. `controlC0` must exist, and the group option grants the non-root container user access when the host audio-group GID differs from the image:

  ```bash
  --device /dev/snd \
  --group-add "$(stat -c '%g' /dev/snd/controlC0)" \
  -e BLURAY_SUBTITLE_MPV_AUDIO_OUTPUT=alsa
  ```

Use `pactl info`, `wpctl status`, and `aplay -l` on the host to identify the available API. Do not expose `/dev/snd` as a fallback when the desktop PipeWire or PulseAudio server is already managing it. A non-Docker Linux source run does not need any of these forwarding options; the host mpv selects its audio output normally.

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
  - Check `DISPLAY` and **mpv** availability. For Docker sound, verify that the selected PulseAudio/PipeWire/ALSA host endpoint exists and use the matching option set from the Docker section.

---

## FAQ

### Does encode auto-crop black borders?

Yes, as an opt-in Encode setting. It analyzes multiple time points without writing screenshots and uses a conservative fixed crop that is safe for all sampled active areas. This handles many constant or changing-border sources, but dark scenes, credits, overlays, and unusual mastering can still produce a wrong result. Always verify the reported margins and the encoded picture; leave the option disabled and use an explicit VPy crop when exact control is required.

### How do I run a short encode test?

For a quick video-side smoke test, add a prefix trim before the final two output lines in VPy:

```python
res = res.std.Trim(first=0, length=720)
```

Keep `first=0` so output-comparison images still use corresponding source and encoded frame numbers. This only shortens the processed video: getnative and selected audio conversion still inspect or process the complete source, while source audio, soft subtitles, and chapters remain untrimmed in the final MKV. HDR10+ is omitted because its full-source timeline no longer matches the VPy output, and this is not a reliable full Dolby Vision test. To test the complete Encode workflow, use a short MKV whose video, audio, subtitles, chapters, and dynamic metadata were cut together.

### Why is remux larger than the original disc?

Usually **duplicated bonus clips** across playlists. Check each MPLS and **View chapters**; if a playlist overlaps the main one, set that MPLS as **main MPLS**, open **View chapters**, uncheck overlapping segments, then **uncheck** the matching rows in the **SP** table below. See the illustrated [Hana-Kimi example](docs/wiki/Interface-Guide.md#example-avoiding-remux-growth-from-duplicated-clips).

### Does encode tag chapters as OP/ED?

No. Remux the disc first, then in encode mode choose **Remux** as the source and use **Edit chapters** to set chapter titles.

### Why does getnative report different native resolutions per episode?

Normal: some discs mix resolutions and authoring is messy. Run a test pass; if results are similar, keep **auto getnative**. Otherwise disable it and edit the VPy with the resolution/scaling you trust—or leave those fields empty.



## Credits

- [tsMuxer](https://github.com/justdan96/tsMuxer)
- [BluRay](https://github.com/lw/BluRay)
- [shinya](https://github.com/shimamura-hougetsu/shinya)
- [ass2bdnxml](https://github.com/Masaiki/ass2bdnxml)
- [BDSup2Sub](https://github.com/mjuhasz/BDSup2Sub)
- [Spp2Pgs](https://github.com/subelf/Spp2Pgs)
- [getnative](https://github.com/Infiziert90/getnative)
- [my-vapoursynth-script](https://github.com/xyx98/my-vapoursynth-script)
