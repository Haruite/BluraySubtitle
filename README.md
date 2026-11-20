# BluraySubtitle

English | [简体中文](README.zh-Hans.md)

Documentation: [project wiki](docs/wiki/Home.md) | [interface guide and examples](docs/wiki/Interface-Guide.md)

Development: [mandatory code modification standards](docs/development/code-standards.md) | [media pipeline and tool selection](docs/development/media-pipeline-and-tool-selection.md) | [refactoring history](docs/refactoring/refactoring-history.md)

- [Latest build directory](https://sbx.mysmy.top/tools/BluraySubtitle/) · [Choose a download](docs/wiki/Packages-and-System-Requirements.md#choose-a-download)
- For versions after 4.7, each release includes the matching packages. [GitHub Releases](https://github.com/Haruite/BluraySubtitle/releases)

BluraySubtitle is a cross-platform GUI tool for Blu-ray workflows. It brings the following five areas of functionality together in one application:

1. **Blu-ray Remux**
2. **Blu-ray Encode**
3. **Blu-ray DIY** (not yet implemented)
4. **Merge Subtitles**
5. **Add Chapters To MKV**

---

## Features and controls

### Interface and settings

- The interface supports English and Simplified Chinese, with Light, Dark, and Colorful themes and adjustable opacity.
- Scroll the page vertically and drag the handle below each table to resize it.
- **Settings** manages general options, fonts, paths, startup defaults, and external tools. Open **Tools** to check for updates or create launch shortcuts.
- Interactive controls and editable cells have a highlighted border. Hover over an editable cell for a tooltip. Double-click a read-only cell for a message that its contents can only be copied.
- The main window runs independently of the terminal by default. View logs in the separate log window.
- Set separate background images for the main and log windows, with individual opacity and blur controls.

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

- x264 supports 8/10-bit, and x265 supports 8/10/12-bit. Standard SVT-AV1 builds support 8/10-bit. The 12-bit choice appears only when the selected encoder supports it.
- Source CFR/VFR timing and audio/video synchronization are preserved. VPy processing must preserve frame correspondence; [prefix tests](#how-do-i-run-a-short-encode-test) are also supported.
- Built-in presets are read-only. Manage user presets under **Advanced** or edit encoder parameters directly.
- Each main/SP row can specify a VPy and per-track FLAC/AAC/Opus conversion. Subtitle modes are external, softsub, and hardsub; Remux sources also support chapter/attachment editing.
- Subtitles from the selected folder fill the main-feature rows in their current order. Check the mapping before encoding.
- The generated VPy provides denoise, dehalo, dering, deband, and anti-aliasing strength controls.
- Automatic getnative can use substantial time and memory and skips sources taller than 1080 pixels. Use the [getnative script](src/scripts/getnative_file.py) for higher-resolution analysis.
- Review automatic cropping visually. Comparison images and frame-check reports are saved under `Compare` and `FrameCheck` in the output folder. Full frame checks may take several times the video's duration.
- Use x265 10-bit to preserve Dolby Vision; x265 10/12-bit supports HDR10+. FEL image residuals cannot be used for encoding and are reported at completion; SVT-AV1 reports that Dolby Vision cannot be retained.

For parameters, filters, preview, and metadata limitations, see [Video Encoding and VapourSynth](docs/wiki/Video-Encoding-and-VapourSynth.md).

### SP management

**Settings → General → Keep SP (bonus features) during Remux** is enabled by default. Turn it off to load discs in Blu-ray Remux or Blu-ray Encode with all SP rows unchecked by default.
Review the SP table after selecting main playlists and episode ranges, then adjust the checked rows. To Remux only SPs, deselect all main playlists and keep the desired SP rows selected. Track edits update output names and formats. Matching commentary tracks can join the main content. See [SP selection, naming, and attachment rules](docs/wiki/Blu-ray-Disc-Structure.md#main-content-and-sp-in-this-project).

## Requirements

When running from source, install the tools needed for the features you use.

### Python packages

The application requires Python 3.10 or later. Install these packages to launch the GUI.

```bash
python -m pip install PyQt6 numpy soundfile pycountry
```

Additional packages depend on the features you use.

- `Pillow` is used for automatic getnative and other image processing.
- Optionally install `psutil` so automatic getnative can use the available memory when the system cannot report it directly.
- `matplotlib` is needed for plots when a custom VPy uses `muvsfunc.getnative()`.
- `PyInstaller` is needed to build distributable packages.

### External tools

Merging subtitles with a BDMV folder requires only the GUI's Python packages above. To read playlists from ISO images, install 7-Zip (`7zz` or `7z`).

| Feature | Tools |
| --- | --- |
| Remux, muxing encoded output, and adding MKV chapters | MKVToolNix (`mkvmerge`, `mkvinfo`, `mkvextract`, `mkvpropedit`) |
| Media inspection, decoding, and audio conversion | `ffmpeg`, `ffprobe` |
| FLAC or AAC audio conversion | `flac` 1.5.0 or later for FLAC, `fdkaac` for AAC |
| Fallback demuxing during Remux | `tsMuxeR` |
| Dynamic HDR metadata | `dovi_tool` for Dolby Vision, `hdr10plus_tool` for HDR10+ |
| ASS subtitle rendering | `libass` for ASSRender |

### Encode mode extras

- The VapourSynth runtime and the plugins used by your `.vpy` scripts.
- `x264`, `x265`, or `SvtAv1EncApp`, depending on which encoder you select.
- `vsedit` for VPy previews.

> Edit and check tool paths under **Settings → External tools**. Leave paths empty to look for installed tools automatically. The paths are saved in `config.json`.

---

## Quick Start

```bash
python src/main.py
```

On desktop, BluraySubtitle runs in a separate process so you can close the launching terminal. Add `--foreground` when starting it from a terminal to see output there too.

On desktops with a system tray, closing the main window sends it to the tray by default and lets tasks continue. Click the tray icon or launch the same installation again to restore the window. Choose **Exit** in the main window or the tray icon’s context menu to quit. You can turn this off under **Settings → General → Minimize to the system tray when closing the main window**.

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

1. Load the Blu-ray chapter source.
2. Load target MKV folder.
3. Verify main MPLS.
4. Run chapter write.

Behavior:

- The Blu-ray source can be a complete BDMV directory or a folder containing only the playlists. Keep the original directory structure. When downloading a disc in qBittorrent, you can select only the `PLAYLIST` folder.
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
- Pass a video path to [`src/scripts/getnative_file.py`](src/scripts/getnative_file.py) to print its getnative result and elapsed time in seconds.

---

## Cross-platform support

Source runs require the [Python dependencies](#python-packages) and external tools for the selected features. For package selection, setup requirements and Docker instructions, see the [wiki](docs/wiki/Packages-and-System-Requirements.md).

### `setup_windows_environment.ps1` (Windows environment setup)

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

Setup uses uv to install the latest stable CPython 3 in a dedicated environment for the application and VapourSynth R79. Run the launch command printed by setup.

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
  - Check subtitle durations. For unusually long subtitles, open the subtitle editor from the context menu. The editor shows the lines with the latest end times first. Correct the end times and save, or select the affected lines and delete them from the context menu.
- **Bonus / extra disc**
  - Uncheck **main MPLS** for that bonus-disc volume.
- **Preview won’t start**
  - Check **`vsedit`** path.
  - Check VPy file and plugins.
- **Linux playback issues**
  - Check the display connection and the selected mpv executable.

---

## FAQ

### How do I run a short encode test?

For a quick video-side smoke test, add a prefix trim before the final two output lines in VPy:

```python
res = res.std.Trim(first=0, length=720)
```

Set `720` to the frame count you need. This trims only video: getnative and audio conversion still process the complete source, and audio, soft subtitles, and chapters remain untrimmed. HDR10+ is omitted, and this is unsuitable for validating a complete Dolby Vision workflow. To test the whole Encode workflow, use a short MKV with video, audio, subtitles, chapters, and dynamic metadata cut together.

### Why is remux larger than the original disc?

Usually **duplicated bonus clips** across playlists. Check each MPLS and **View chapters**; if a playlist overlaps the main one, set that MPLS as **main MPLS**, open **View chapters**, uncheck overlapping segments, then **uncheck** the matching rows in the **SP** table below. See the illustrated [Hana-Kimi example](docs/wiki/Interface-Guide.md#example-avoiding-remux-growth-from-duplicated-clips).

### Does encode tag chapters as OP/ED?

Add OP and ED labels manually. Remux the disc first, then select **Remux** as the source in Blu-ray Encode and use **Edit chapters** to set the titles.

### Why does getnative report different native resolutions per episode?

Blu-ray authoring can combine footage at different native resolutions, which makes the source resolution harder to identify. Run a test pass first. If results are similar across episodes, use **auto getnative**. If they vary, turn it off and enter the native resolution and scaling algorithm you want in the VPy, or leave those settings unset.

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
