# Third-party notices (bundled binaries)

**Product:** BluraySubtitle (Windows, PyInstaller one-folder build)

Versioned fields are refreshed from the selected bundled artifacts when `BluraySubtitle_windows_x64.spec` runs.

---

## FFmpeg / FFprobe

- **Files:** `ffmpeg.exe`, `ffprobe.exe`
- **Shipped build:** `ffmpeg-{{FFMPEG_BUILD}}`
- **License:** GPL v3
- **Source for this build:** https://github.com/FFmpeg/FFmpeg/tree/n{{FFMPEG_VERSION}}

**Trademark:** If you redistribute FFmpeg binaries, follow FFmpeg’s trademark policy: https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **Files:** `flac.exe`, `libFLAC.dll`
- **Version:** {{FLAC_VERSION}}
- **License:** BSD-3-Clause
- **Source:** https://ftp.osuosl.org/pub/xiph/releases/flac/flac-{{FLAC_VERSION}}.tar.xz

---

## fdkaac (command-line encoder) + FDK-AAC (library)

These are **two separate upstreams**: the `fdkaac` program links against or ships with the **FDK-AAC** library build.

### fdkaac — https://github.com/nu774/fdkaac

- **Bundled file(s):** `fdkaac.exe`
- **Version:** **v{{FDKAAC_VERSION}}**
- **License:**
  - Most of the project: **Zlib License** — SPDX: **`Zlib`**
  - Bundled sources also include **MIT** (e.g. `parson`), **BSD-4-clause** (e.g. `getopt`), and **BSD-style** (e.g. `lpc.c` / `lpc.h`) as listed in the same `COPYING` file.
- **Full license text (this tag):** https://raw.githubusercontent.com/nu774/fdkaac/v{{FDKAAC_VERSION}}/COPYING
- **Source code (tagged tree):** https://github.com/nu774/fdkaac/tree/v{{FDKAAC_VERSION}}
- **Source archive (reproducible tarball):** https://github.com/nu774/fdkaac/archive/refs/tags/v{{FDKAAC_VERSION}}.tar.gz

### Fraunhofer FDK AAC Codec Library — https://github.com/mstorsjo/fdk-aac

- **Bundled component:** statically linked into `fdkaac.exe`
- **Version:** **v{{FDK_AAC_VERSION}}**
- **License:** **Fraunhofer “Software License for The Fraunhofer FDK AAC Codec Library for Android”** — a **project-specific** license (upstream ships it as **`NOTICE`**). It is **not** Apache-2.0 or LGPL; there is **no single widely used SPDX identifier** for it (some manifests use a custom `LicenseRef-…` after internal policy).
- **Full license text (this tag):** https://raw.githubusercontent.com/mstorsjo/fdk-aac/v{{FDK_AAC_VERSION}}/NOTICE
- **Source code (tagged tree):** https://github.com/mstorsjo/fdk-aac/tree/v{{FDK_AAC_VERSION}}
- **Source archive (reproducible tarball):** https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v{{FDK_AAC_VERSION}}.tar.gz

**Redistribution notes:** in particular, binary redistributions are expected to **retain the complete license text** in documentation or accompanying materials, and to **make the complete source of the FDK AAC Codec (and your modifications, if any) available without charge** to recipients of binaries — **and this license does not grant patent rights**; AAC may require separate patent licensing for some uses (upstream points to Via Licensing / patent holders).

**Patent / product compliance:** this section is **not legal advice**. If you distribute AAC encoders to end users, confirm **patent / licensing** requirements for your product and territory separately from “copyright license” text above.

---

## x264

- **Files:** `x264.exe`, `/usr/bin/x264`
- **Version:** `{{X264_VERSION}}`
- **License:** GPL-2.0
- **Official repository:** https://code.videolan.org/videolan/x264.git
- **Build note:** built from the unmodified official source as an 8/10-bit-capable CLI; the Windows setup additionally uses PGO.

---

## x265

- **Files:** `x265.exe`, `/usr/bin/x265`
- **Version:** {{X265_VERSION}}
- **License:** GPL-2.0
- **Source for this build:** https://github.com/Multicorewareinc/x265/tree/{{X265_VERSION}}
- **Build note:** built from the official source as a statically linked 8/10/12-bit multilib CLI with native HDR10+ JSON input support on the target platform, including Ubuntu 26.04 for Docker. The managed build adds the missing `<cstdint>` include to upstream `dynamicHDR10/json11/json11.cpp` for compatibility with current C++ compilers.

---

## SVT-AV1 (SvtAv1EncApp)

- **Files:** `SvtAv1EncApp.exe`
- **Version:** v{{SVT_AV1_VERSION}}
- **License:** BSD 3-Clause
- **Source:** https://gitlab.com/AOMediaCodec/SVT-AV1/-/archive/v{{SVT_AV1_VERSION}}/SVT-AV1-v{{SVT_AV1_VERSION}}.zip
- **Build note:** The bundled Windows encoder was built from this tag with the 12-bit application patch documented in `setup_linux_environment.sh` and `Dockerfile`; 8/10/12-bit encoding was tested.

---

## tsMuxeR

- **Files:** `tsMuxeR.exe`
- **Version:** v{{TSMUXER_VERSION}}
- **License:** Apache-2.0
- **Source:** https://github.com/justdan96/tsMuxer/archive/refs/tags/{{TSMUXER_VERSION}}.zip

---

## dovi_tool

- **Files:** `dovi_tool.exe`
- **Version:** {{DOVI_TOOL_VERSION}}
- **License:** MIT
- **Source:** https://github.com/quietvoid/dovi_tool/archive/refs/tags/{{DOVI_TOOL_VERSION}}.zip

---

## hdr10plus_tool

- **Files:** `hdr10plus_tool.exe`, `/usr/bin/hdr10plus_tool`
- **Version:** {{HDR10PLUS_TOOL_VERSION}}
- **License:** MIT
- **Source for this build:** https://github.com/quietvoid/hdr10plus_tool/tree/{{HDR10PLUS_TOOL_VERSION}}
- **Build note:** Windows setup downloads the official MSVC release; Linux setup and Docker download the official musl release built upstream with its internal font feature. The tool is not compiled locally.

---

## truehdd

- **Files:** `truehdd.exe`
- **Version:** {{TRUEHDD_VERSION}}
- **License:** Apache 2.0
- **Source:** https://github.com/truehdd/truehdd/archive/refs/tags/{{TRUEHDD_VERSION}}.zip

---

## libass

- **Files:** `libass-9.dll`
- **Version:** {{LIBASS_VERSION}}
- **License:** ISC
- **Source:** https://github.com/libass/libass/archive/refs/tags/{{LIBASS_VERSION}}.zip
- **Build:** MSYS2 UCRT64 shared libass with its non-system dependencies linked statically. Fontconfig is disabled in favor of the Windows DirectWrite/GDI font provider; libunibreak and x86 assembly are enabled. The packaged DLL imports only Windows system DLLs.
- **Statically linked components:** FreeType (FTL/GPL), FriBidi (LGPL-2.1-or-later), HarfBuzz (MIT), libunibreak (Zlib), GNU libiconv/gettext (LGPL), GLib (LGPL-2.1-or-later), PCRE2 (BSD), Graphite2 (MPL/LGPL/GPL), Brotli (MIT), bzip2, libpng, zlib, and the GCC/MinGW runtime libraries (GPL with the GCC Runtime Library Exception). Source and license metadata are available from https://packages.msys2.org/.

---

## MKVToolNix

- **Files:** `mkvmerge.exe`, `mkvextract.exe`, `mkvinfo.exe`, `mkvpropedit.exe`
- **Version:** v{{MKVTOOLNIX_VERSION}}
- **License:** GPL v2
- **Full license text:** https://codeberg.org/mbunkus/mkvtoolnix/raw/branch/main/COPYING
- **Source:** https://codeberg.org/mbunkus/mkvtoolnix/archive/release-{{MKVTOOLNIX_VERSION}}.zip
- **Notes:** Additional bundled libraries and assets are listed in upstream `README.md` (section “Included third-party components and their licenses”) under `doc/licenses/`.

---

## VapourSynth portable bundle (`vs_pkg/`)

The `vs_pkg/` directory in the PyInstaller bundle mirrors a **Windows x64 portable layout**. It is composed of the following **documented upstreams** plus any extra plugin DLLs you add locally.

### VapourSynth-Classic (core runtime, `vspipe`, etc.)

- **Upstream:** https://github.com/AmusementClub/vapoursynth-classic
- **Release / tag:** {{VAPOURSYNTH_CLASSIC_VERSION}}
- **License:** **GNU Lesser General Public License v3** — SPDX: **`LGPL-3.0-or-later`**
- **Full license text (this tag):** https://raw.githubusercontent.com/AmusementClub/vapoursynth-classic/{{VAPOURSYNTH_CLASSIC_VERSION}}/COPYING.LESSER
- **Source archive:** https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/{{VAPOURSYNTH_CLASSIC_VERSION}}.zip

### CPython — Windows embeddable distribution

- **Files (typical):** `python313.dll`, embeddable stdlib zip, and related files from the **embed** layout under `vs_pkg/`
- **Version:** {{PYTHON_VERSION}} (amd64 embeddable zip)
- **Downloaded from:** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/python-{{PYTHON_VERSION}}-embed-amd64.zip
- **License:** **Python Software Foundation License** — SPDX: **`PSF-2.0`**
- **License overview:** https://docs.python.org/3/license.html
- **Corresponding source (CPython):** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/Python-{{PYTHON_VERSION}}.tgz

### VapourSynthScripts + bundled filters (AmusementClub/tools)

- **Upstream packages:** assets from **https://github.com/AmusementClub/tools/releases** .
- **Version:** {{VAPOURSYNTH_TOOLS_VERSION}}
- **License:** the **tools** repository does **not** publish a single root `LICENSE` file on GitHub; components may differ.

---

### VapourSynth Editor

- **Files:** `vsedit.exe`
- **Version:** {{VSEDIT_VERSION}}
- **License:** MIT
- **Source:** https://github.com/YomikoR/VapourSynth-Editor/archive/refs/tags/{{VSEDIT_VERSION}}.zip

---

## PyInstaller runtime

- **Files:** Bootloader and frozen Python runtime in the one-folder bundle.
- **Version:** {{PYINSTALLER_VERSION}}
- **License:** PyInstaller is **GPL-2.0-or-later** with a runtime exception for the bootloader’s effect on your app — read current PyInstaller `COPYING.txt`: https://github.com/pyinstaller/pyinstaller
- **Source:** https://github.com/pyinstaller/pyinstaller/releases/{{PYINSTALLER_VERSION}}

---
