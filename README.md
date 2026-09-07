# BluraySubtitle

English | [简体中文](README.zh-Hans.md)

Documentation: [project wiki](docs/wiki/Home.md) | [interface guide and examples](docs/wiki/Interface-Guide.md)

Development: [mandatory code modification standards](docs/development/code-standards.md) | [media pipeline and tool selection](docs/development/media-pipeline-and-tool-selection.md) | [refactoring history](docs/refactoring/refactoring-history.md)

The Windows x64 release is a one-folder package. Extract the complete archive, then run `BluraySubtitle_windows_x64.exe` without separating it from `_internal`. Configuration is stored in `config.json` in the program directory, or the repository root for source runs; ensure that directory is writable.

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
- Scroll the page vertically and drag the handle below each table to resize it. See the [interface guide](docs/wiki/Interface-Guide.md#main-window-content-areas) for layout and table controls.
- **Settings** manages general options, paths, startup defaults, external tools, and manual updates.
- Series mode splits by chapters; movie mode keeps a continuous output. Each disc can have multiple selected main MPLS files. Review automatic selections, episode ranges, and tracks before running.

### Remux controls

Choose video, audio, and subtitles in **Edit Tracks**. Edit the command for a main MPLS when needed; manually entered track-selection flags are replaced by the UI choices.

- **Allow partially missing non-video tracks** is disabled by default. It permits gaps from missing audio/subtitle intervals; missing video or a whole selected track still fails. See [missing-track handling](docs/development/media-pipeline-and-tool-selection.md#3-track-aligned-remux-fallback).
- **Trim copyright bumper** attempts to remove short trailing copyright clips. Review the result; see the [conditions](docs/wiki/Blu-ray-Disc-Structure.md#short-copyright-bumpers-at-the-end).
- Selected external subtitles are soft-muxed into the main MKV.
- **Mux Dolby Vision** converts MEL to profile 8.1 and retains profile 7 for FEL or unrecognized enhancement layers; disabling it excludes the enhancement layer. See [Dolby Vision layer handling](docs/wiki/Media-Formats-and-Dolby-Vision.md#profile-81-in-this-project).

### Audio controls

- Remux preserves lossy audio and converts lossless audio to FLAC by default. Configure conversion and compression levels under **Advanced**.
- **Convert DTS:X and TrueHD Atmos to FLAC during Remux** starts disabled because FLAC cannot retain object metadata.
- Remux and Encode remove silent and exact duplicate audio tracks, reporting each removal; standalone single-track audio is excluded.
- Converted tracks with gaps require a Matroska container. Keep the `.audio-gaps.json` beside Remux outputs for subsequent encoding.
- A failed conversion or duration loss above the configurable threshold (default 1 second) keeps the original track.

See [audio formats and conversion targets](docs/wiki/Media-Formats-and-Dolby-Vision.md#lossless-audio-conversion-decisions) for format choices, and [media processing](docs/development/media-pipeline-and-tool-selection.md#audio-processing) for cleanup and validation rules.

### Encode controls

- Choose bundled/system `vspipe` and encoders: x264 supports 8/10-bit, x265 8/10/12-bit, and SVT-AV1 8/10-bit. The experimental SVT-AV1 12-bit option is unusable.
- Source CFR/VFR timing and audio/video synchronization are preserved. VPy processing must preserve frame correspondence; [prefix tests](#how-do-i-run-a-short-encode-test) are also supported.
- Built-in presets are read-only. Manage user presets under **Advanced** or edit encoder parameters directly.
- Each main/SP row can specify a VPy and per-track FLAC/AAC/Opus conversion. Subtitle modes are external, softsub, and hardsub; Remux sources also support chapter/attachment editing.
- The generated VPy provides denoise, dehalo, dering, deband, and anti-aliasing strength controls.
- Automatic getnative can use substantial time and memory and skips sources taller than 1080 pixels. Use the [getnative script](src/scripts/getnative_file.py) for higher-resolution analysis.
- Review automatic cropping visually. Comparison images and frame-check reports are saved under `Compare` and `FrameCheck` in the output folder. Full frame checks may take several times the video's duration.
- Use x265 10/12-bit to preserve Dolby Vision; it also supports HDR10+. FEL image residuals cannot be used for encoding and are reported at completion; SVT-AV1 reports that Dolby Vision cannot be retained.

For parameters, filters, preview, and metadata limitations, see [Video Encoding and VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.md).

### SP management

Review the SP table after selecting main playlists and episodes, and deselect unwanted content. Track edits update output names and formats; matching commentary tracks can join the main content. See [SP selection, naming, and attachment rules](docs/wiki/Blu-ray-Disc-Structure.md#main-content-and-sp-in-this-project).

## Requirements

### Python packages

- `PyQt6`
- `numpy`
- `soundfile`
- `pycountry`
- `Pillow`
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
- `hdr10plus_tool` (HDR10+)
- `dovi_tool` (Dolby Vision)
- `SvtAv1EncApp`
- `fdkaac`

> Configure paths and check tool availability under **Settings > External tools**. Encode can use bundled or system tools.

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

- Folders can include ISO files larger than 5 GiB; merged subtitles are saved beside each image with the same base name. ISO input is limited to subtitle merging.
- If mapping fails, check **main MPLS** first.
- If subtitle order is wrong, **click the filename column header** to sort, or drag rows to reorder.
- If a subtitle duration looks impossible, fix the subtitle file first (right-click **edit** prioritizes lines with the latest end times; fix ends or delete bad lines).
- SRT, ASS, SSA, and SUP are supported. Subtitle formats cannot be mixed within one merged output.
- Results are saved beside the disc folder and its main playlist. Existing outputs cause an error and are not overwritten.
- Multiple main playlists selected from one disc are merged independently. Their disc-folder-adjacent files append the MPLS stem to avoid filename collisions.

## 2) Add Chapters To MKV

Typical flow:

1. Load Blu-ray chapter source (playlist/chapter info).
2. Load target MKV folder.
3. Verify main MPLS.
4. Run chapter write.

Behavior:

- MKVs are matched to main-playlist chapters in table order; check the order first.
- **Edit Original File Directly** writes to the source MKV; otherwise, results go to the source directory's `output` subfolder.
- Incomplete chapter matching or existing outputs stop the operation before writing.

## 3) Blu-ray Remux

Typical flow:

1. Load Blu-ray folder.
2. (Optional) Load subtitle folder.
3. Verify main MPLS and chapter span.
4. (Optional) Edit remux command.
5. Choose output folder and run.

Check [Remux settings](#remux-controls) and output names before running. Existing or duplicate outputs stop the task without overwriting files.

## 4) Blu-ray Encode

Typical flow:

1. Choose input source (**Blu-ray / Remux**).
2. Configure VPy, encoder, subtitle packaging, etc.
3. (Optional) Edit tracks / **select all tracks**.
4. (Optional) Set **start / end chapter** per row.
5. Run encode.

Blu-ray input rejects existing outputs. Remux input skips completed main/SP, external-subtitle, and companion outputs and continues the remaining work, allowing interrupted encodes to resume. Empty main/SP files cause an error and must be addressed first.

---

## VPy Editing and Preview

- **Edit script** uses the system-associated editor; **Preview script** uses `vsedit`. The default script is `vpy.vpy`.
- The default VPy supports comparing processed and source frames. See [VSEdit preview and snapshots](docs/wiki/Video-Encoding-and-VapourSynth.md#previewing-processed-and-source-frames-in-vsedit).
- Prepare interlaced, telecined, and mixed-cadence sources using the [preprocessing instructions](docs/wiki/Video-Encoding-and-VapourSynth.md#interlaced-telecined-and-mixed-cadence-sources).

---

## Repository helper scripts

- [`src/scripts/batch_remux_movie.py`](src/scripts/batch_remux_movie.py): edit its paths or pass them on the command line to batch-remux every BDMV under one movie folder.
- [`src/scripts/getnative_file.py`](src/scripts/getnative_file.py): edit `video_file` and run it directly to print one video's automatic getnative result and elapsed seconds.

---

## `setup_windows_environment.ps1` (Windows environment setup)

`setup_windows_environment.ps1` configures the runtime and build environment for **x64 Windows client and Windows Server systems**.

Before the first run, set the current user’s PowerShell execution policy, then start the setup from the repository root:

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

Use `pactl info`, `wpctl status`, and `aplay -l` on the host to identify the available API. Do not expose `/dev/snd` as a fallback when the desktop PipeWire or PulseAudio server is already managing it.

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

Yes. Enable the option and verify the reported margins and encoded picture. Dark scenes, credits, and unusual borders can produce incorrect results; disable it and specify a VPy crop when exact control is needed. See [automatic cropping](docs/wiki/Video-Encoding-and-VapourSynth.md#automatic-black-border-cropping) for the method.

### How do I run a short encode test?

For a quick video-side smoke test, add a prefix trim before the final two output lines in VPy:

```python
res = res.std.Trim(first=0, length=720)
```

Set `720` to the frame count you need. This trims only video: getnative and audio conversion still process the complete source, and audio, soft subtitles, and chapters remain untrimmed. HDR10+ is omitted, and this is unsuitable for validating a complete Dolby Vision workflow. To test the whole Encode workflow, use a short MKV with video, audio, subtitles, chapters, and dynamic metadata cut together.

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
