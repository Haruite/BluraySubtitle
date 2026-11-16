# BluraySubtitle

English | [简体中文](README.zh-Hans.md)

Documentation: [project wiki](docs/wiki/Home.md) | [interface guide and examples](docs/wiki/Interface-Guide.md)

Development: [mandatory code modification standards](docs/development/code-standards.md) | [media pipeline and tool selection](docs/development/media-pipeline-and-tool-selection.md) | [refactoring history](docs/refactoring/refactoring-history.md)

The x64 package supports **Windows 10 version 1809 or later**. The ARM64 package targets **Windows 10 or later on ARM64**. The earliest Windows 10 release for the ARM64 package is pending verification. **Windows 10 22H2** is recommended.

- Latest builds from `main`. [Windows x64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_windows_x64.7z) · [Windows ARM64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_windows_arm64.7z) · [Ubuntu 26.04 x64](https://sbx.mysmy.top/tools/BluraySubtitle/BluraySubtitle_ubuntu26.04_x64.tar.xz)
- Versioned packages are attached to the matching release. [GitHub Releases](https://github.com/Haruite/BluraySubtitle/releases)

BluraySubtitle is a GUI tool for Blu-ray workflows on **Windows / Linux**. It brings the following five areas of functionality together in one application:

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
- **Settings** manages general options, fonts, paths, startup defaults, and external tools. Open **Tools** to check for updates or create launch shortcuts.
- Check the discs to process and drag their paths to set the order. Series mode splits by chapters; movie mode keeps a continuous output and can select alternate cuts by default. Each disc can have multiple selected main MPLS files. Review automatic selections, episode ranges, and tracks before running.

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
- Converted tracks with gaps require a Matroska container.
- **Save .audio-gaps.json during Remux** in **Settings → Advanced → Audio encoding** is off by default. If you plan to encode the Remux output later, enable the option and keep the `.audio-gaps.json` file beside the output so Encode can reuse the audio gap information.
- A failed conversion or duration loss above the configurable threshold (default 1 second) keeps the original track.

See [audio formats and conversion targets](docs/wiki/Media-Formats-and-Dolby-Vision.md#lossless-audio-conversion-decisions) for format choices, and [media processing](docs/development/media-pipeline-and-tool-selection.md#audio-processing) for cleanup and validation rules.

### Encode controls

- Choose bundled/system `vspipe` and encoders: x264 supports 8/10-bit and x265 8/10/12-bit. Standard SVT-AV1 builds support 8/10-bit; the 12-bit choice appears only when the selected encoder supports it.
- Source CFR/VFR timing and audio/video synchronization are preserved. VPy processing must preserve frame correspondence; [prefix tests](#how-do-i-run-a-short-encode-test) are also supported.
- Built-in presets are read-only. Manage user presets under **Advanced** or edit encoder parameters directly.
- Each main/SP row can specify a VPy and per-track FLAC/AAC/Opus conversion. Subtitle modes are external, softsub, and hardsub; Remux sources also support chapter/attachment editing.
- For Remux sources, subtitles from the selected folder fill the existing main rows in their current order. Check the mapping before encoding.
- The generated VPy provides denoise, dehalo, dering, deband, and anti-aliasing strength controls.
- Automatic getnative can use substantial time and memory and skips sources taller than 1080 pixels. Use the [getnative script](src/scripts/getnative_file.py) for higher-resolution analysis.
- Review automatic cropping visually. Comparison images and frame-check reports are saved under `Compare` and `FrameCheck` in the output folder. Full frame checks may take several times the video's duration.
- Use x265 10-bit to preserve Dolby Vision; x265 10/12-bit supports HDR10+. FEL image residuals cannot be used for encoding and are reported at completion; SVT-AV1 reports that Dolby Vision cannot be retained.

For parameters, filters, preview, and metadata limitations, see [Video Encoding and VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.md).

### SP management

**Settings → General → Keep SP (bonus features) during Remux** is enabled by default. Turn it off to start with an unchecked SP table when loading a disc in Blu-ray Remux or Blu-ray Encode. You can still select SP rows manually.
Review the SP table after selecting main playlists and episodes, and deselect unwanted content. To Remux only SPs, deselect all main playlists and keep the desired SP rows selected. Track edits update output names and formats; matching commentary tracks can join the main content. See [SP selection, naming, and attachment rules](docs/wiki/Blu-ray-Disc-Structure.md#main-content-and-sp-in-this-project).

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

- VapourSynth Python module, runtime, and required plugins (installed by the environment setup script)
- `vspipe`
- `vsedit`
- `x264`
- `x265`
- `hdr10plus_tool` (HDR10+)
- `dovi_tool` (Dolby Vision)
- `SvtAv1EncApp`
- `fdkaac`

> Edit and check tool paths under **Settings → External tools**. The paths are saved in `config.json`. Relative paths start from the directory containing that file.

---

## Quick Start

```bash
python src/main.py
```

On desktop, BluraySubtitle runs in a separate process so you can close the launching terminal. Add `--foreground` when starting it from a terminal to see output there. For live output in the GUI and optional file saving, see the [application log](docs/wiki/Interface-Guide.md#application-log).

On desktops with a system tray, closing the main window sends it to the tray by default and lets tasks continue. Click the tray icon or launch the same installation again to restore the window. Choose **Exit** in the main window or the tray icon’s context menu to quit. You can turn this off under **Settings → General → Minimize to the system tray when closing the main window**.

Set optional background images for the main and log windows under **Settings → Paths**. [Window backgrounds](docs/wiki/Interface-Guide.md#window-backgrounds)

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

- **Edit script** uses the system-associated editor. **Preview script** uses `vsedit`. The default script is generated as `vpy/vpy_<id>.vpy` next to `config.json`. When previewing the default script, VSEdit opens a temporary copy with the row's video and subtitle paths filled in. Saved filter edits are applied to the default script when VSEdit closes.
- The default VPy supports comparing processed and source frames. See [VSEdit preview and snapshots](docs/wiki/Video-Encoding-and-VapourSynth.md#previewing-processed-and-source-frames-in-vsedit).
- Prepare interlaced, telecined, and mixed-cadence sources using the [preprocessing instructions](docs/wiki/Video-Encoding-and-VapourSynth.md#interlaced-telecined-and-mixed-cadence-sources).

---

## Repository helper scripts

- [`src/scripts/batch_remux_movie.py`](src/scripts/batch_remux_movie.py): edit its paths or pass them on the command line to batch-remux every BDMV under one movie folder.
- Run `python src/scripts/getnative_file.py "path/to/video.mkv"` to print the getnative result and elapsed seconds for one video.

---

## Cross-platform support

### `setup_windows_environment.ps1` (Windows environment setup)

The script configures source runs on **x64 Windows 10 version 1909 or later**, **x64 Windows Server 2019 or later with Desktop Experience**, and **ARM64 Windows 11 or later**. Setup defaults to VapourSynth R79 on both architectures. Use `-VapourSynthRuntime Classic` to select the Classic runtime. On ARM64, that option uses a private x64 Python and x64 builds of the Classic plugins and VSEdit.

For the first run, set the current user’s PowerShell execution policy and start setup from the repository root.

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.\setup_windows_environment.ps1
```

The script requests administrator permission, asks for the display language, and can be rerun after interruption. Downloads use the configured **Windows system proxy** automatically. Configure it before starting setup if direct access to the download sources is unavailable.

To package the configured runtime environment, run the command for your architecture from the repository root.

```powershell
pyinstaller BluraySubtitle_windows_x64.spec
```

```powershell
pyinstaller BluraySubtitle_windows_arm64.spec
```

### `setup_linux_environment.sh` (Linux runtime environment)

The script builds the runtime environment for **x64 Linux** distributions in either family.

- Ubuntu 22.04 or later, including distributions based on these Ubuntu releases.
- Debian 12 or later, including distributions based on these Debian releases.

Setup installs VapourSynth R79. On distributions with an older system Python, it installs a dedicated Python 3.12 and prints the launch command to use.

Earlier versions of the setup script were tested in the following x64 WSL 2 environments.

- Ubuntu 22.04, 24.04, 26.04, and 26.10
- Debian 12 and 13
- Kali Linux 2022.4 and Kali Rolling
- Linux Mint 22.3
- LMDE 7
- antiX 23.2 and 26.1
- Devuan 6
- KDE neon
- Pop!_OS 24.04

Use a regular account with `sudo` access. Running the script directly as `root` is not guaranteed to succeed. Make the script executable before the first run and start it from the repository root.

```bash
chmod +x setup_linux_environment.sh
./setup_linux_environment.sh
```

See [Linux desktop mpv](docs/wiki/Media-Formats-and-Dolby-Vision.md#linux-desktop-playback-with-mpv) for playback presets and subtitle fonts.

When run over SSH, `setup_linux_environment.sh` uses **tmux** to display build logs.

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
- **Linux playback issues**
  - Check the display connection and the selected mpv executable.

---

## FAQ

### Why aren't older operating systems supported?

Older systems require extra compatibility patches and testing for Python, Qt, and multimedia dependencies. The maintenance cost is too high to extend the current support range.

### Which Linux distributions can run the packaged build?

The PyInstaller build targets Ubuntu 26.04 x64 and includes the multimedia tools and VapourSynth runtime. On other unsupported systems, you can use Docker to run the extracted program. See [Run the Ubuntu package in Docker](docs/wiki/Run-Ubuntu-Package-in-Docker.md).

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
- [mpv_PlayKit (mpv-lazy)](https://github.com/hooke007/mpv_PlayKit)
