# Third-party notices (bundled binaries)

**Product:** BluraySubtitle (Windows, PyInstaller onefile build)  

---

## FFmpeg / FFprobe

- **Files:** `ffmpeg.exe`, `ffprobe.exe`
- **Shipped build (from spec):** `ffmpeg-8.1-essentials_build` 
- **License:** GPL v3
- **Source for this build:** https://github.com/FFmpeg/FFmpeg/commit/4867d251ad

**Trademark:** If you redistribute FFmpeg binaries, follow FFmpeg’s trademark policy: https://ffmpeg.org/legal.html

---

## FLAC / metaflac / libFLAC / libFLAC++

- **Files:** `flac.exe`, `metaflac.exe`, `libFLAC.dll`, `libFLAC++.dll`
- **Version:** 1.5.0
- **License:** BSD-3-Clause
- **Source:** https://ftp.osuosl.org/pub/xiph/releases/flac/flac-1.5.0.tar.xz

---

## fdkaac (command-line encoder) + FDK-AAC (library)

These are **two separate upstreams**: the `fdkaac` program links against or ships with the **FDK-AAC** library build.

### fdkaac — https://github.com/nu774/fdkaac

- **Bundled file(s):** `fdkaac.exe`
- **Version:** **v1.0.7** (Git commit `057f83220a14a1297559b01e7884d7693a3fce29`)
- **License:**
  - Most of the project: **Zlib License** — SPDX: **`Zlib`**
  - Bundled sources also include **MIT** (e.g. `parson`), **BSD-4-clause** (e.g. `getopt`), and **BSD-style** (e.g. `lpc.c` / `lpc.h`) as listed in the same `COPYING` file.
- **Full license text (this tag):** https://raw.githubusercontent.com/nu774/fdkaac/v1.0.7/COPYING
- **Source code (tagged tree):** https://github.com/nu774/fdkaac/tree/v1.0.7  
- **Source archive (reproducible tarball):** https://github.com/nu774/fdkaac/archive/refs/tags/v1.0.7.tar.gz

### Fraunhofer FDK AAC Codec Library — https://github.com/mstorsjo/fdk-aac

- **Bundled file(s):** `fdk-aac.lib`
- **Version:** **v2.0.3** (Git commit `716f4394641d53f0d79c9ddac3fa93b03a49f278` — peeled from tag `v2.0.3`)
- **License:** **Fraunhofer “Software License for The Fraunhofer FDK AAC Codec Library for Android”** — a **project-specific** license (upstream ships it as **`NOTICE`**). It is **not** Apache-2.0 or LGPL; there is **no single widely used SPDX identifier** for it (some manifests use a custom `LicenseRef-…` after internal policy).
- **Full license text (this tag):** https://raw.githubusercontent.com/mstorsjo/fdk-aac/v2.0.3/NOTICE
- **Source code (tagged tree):** https://github.com/mstorsjo/fdk-aac/tree/v2.0.3  
- **Source archive (reproducible tarball):** https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v2.0.3.tar.gz

**Redistribution notes:** in particular, binary redistributions are expected to **retain the complete license text** in documentation or accompanying materials, and to **make the complete source of the FDK AAC Codec (and your modifications, if any) available without charge** to recipients of binaries — **and this license does not grant patent rights**; AAC may require separate patent licensing for some uses (upstream points to Via Licensing / patent holders).

**Patent / product compliance:** this section is **not legal advice**. If you distribute AAC encoders to end users, confirm **patent / licensing** requirements for your product and territory separately from “copyright license” text above.

---

## x264

- **Files:** `x264.exe`
- **Version:** r3214
- **License:** GPL-2.0
- **Source:** https://github.com/jpsdr/x264/archive/refs/tags/r3214.zip

---

## x265

- **Files:** `x265.exe`
- **Version:** Asuna-2.8
- **License:** GPL-2.0
- **Source:** https://github.com/msg7086/x265-Yuuki-Asuna/archive/refs/tags/Asuna-2.8.zip

---

## SVT-AV1 (SvtAv1EncApp)

- **Files:** `SvtAv1EncApp.exe`
- **Version:** v4.1.0
- **License:** BSD 3-Clause
- **Source:** https://gitlab.com/AOMediaCodec/SVT-AV1/-/archive/v4.1.0/SVT-AV1-v4.1.0.zip

---

## tsMuxeR

- **Files:** `tsMuxeR.exe`
- **Version:** v2.7.0
- **License:** Apache-2.0
- **Source:** https://github.com/justdan96/tsMuxer/archive/refs/tags/2.7.0.zip

---

## libass

- **Files:** `libass-9.dll` 
- **Version:** 0.17.4
- **License:** ISC 
- **Source:** https://github.com/libass/libass/archive/refs/tags/0.17.4.zip

---

## MKVToolNix

- **Files:** `mkvmerge.exe`, `mkvextract.exe`, `mkvinfo.exe`, `mkvpropedit.exe`
- **Version:** v98.0
- **License:** GPL v2
- **Full license text:** https://codeberg.org/mbunkus/mkvtoolnix/raw/branch/main/COPYING
- **Source:** https://codeberg.org/mbunkus/mkvtoolnix/archive/release-98.0.zip
- **Notes:** Additional bundled libraries and assets are listed in upstream `README.md` (section “Included third-party components and their licenses”) under `doc/licenses/`.

---

## VapourSynth portable bundle (`vs_pkg/`)

The `vs_pkg/` directory in the PyInstaller bundle mirrors a **Windows x64 portable layout**. It is composed of the following **documented upstreams** plus any extra plugin DLLs you add locally.

### VapourSynth-Classic (core runtime, `vspipe`, etc.)

- **Upstream:** https://github.com/AmusementClub/vapoursynth-classic  
- **Release / tag:** R57.A12  
- **License:** **GNU Lesser General Public License v3** — SPDX: **`LGPL-3.0-or-later`**  
- **Full license text (this tag):** https://raw.githubusercontent.com/AmusementClub/vapoursynth-classic/R57.A12/COPYING.LESSER  
- **Source archive:** https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/R57.A12.zip  

### CPython — Windows embeddable distribution

- **Files (typical):** `python313.dll`, embeddable stdlib zip, and related files from the **embed** layout under `vs_pkg/`  
- **Version:** 3.13.13 (amd64 embeddable zip)  
- **Downloaded from:** https://www.python.org/ftp/python/3.13.13/python-3.13.13-embed-amd64.zip  
- **License:** **Python Software Foundation License** — SPDX: **`PSF-2.0`**   
- **License overview:** https://docs.python.org/3/license.html  
- **Corresponding source (CPython):** https://www.python.org/ftp/python/3.13.13/Python-3.13.13.tgz  

### VapourSynthScripts + bundled filters (AmusementClub/tools)

- **Upstream packages:** assets from **https://github.com/AmusementClub/tools/releases** .  
- **Version:** 2025H1p 
- **License:** the **tools** repository does **not** publish a single root `LICENSE` file on GitHub; components may differ. 

---

## PyInstaller runtime

- **Files:** Bootloader and extracted stdlib in the onefile bundle.
- **License:** PyInstaller is **GPL-2.0-or-later** with a runtime exception for the bootloader’s effect on your app — read current PyInstaller `COPYING.txt`: https://github.com/pyinstaller/pyinstaller  
- **Source:**  https://github.com/pyinstaller/pyinstaller/releases/6.20.0

---
