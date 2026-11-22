# Third-party notices (bundled binaries)

**Product:** BluraySubtitle (macOS, {{PYTHON_ARCHITECTURE}})

BluraySubtitle is copyright © 2024 Haruite and distributed under the [MIT License](BluraySubtitle-LICENSE.txt). File paths below start at `Contents/Resources/Runtime/` inside the application.

---

## 7-Zip

- **Files:** `bin/7zz`
- **Version:** {{SEVEN_ZIP_VERSION}}
- **License:** GNU LGPL, with BSD-3-Clause portions and the unRAR restriction
- **Source:** https://github.com/ip7z/7zip/tree/{{SEVEN_ZIP_VERSION}}
- **License text:** https://www.7-zip.org/license.txt

---

## FFmpeg / FFprobe

- **Files:** `bin/ffmpeg`, `bin/ffprobe`
- **Version:** `ffmpeg-{{FFMPEG_VERSION}}`
- **License:** LGPL-2.1-or-later as built. The bundled program prints its license with `-L`.
- **Source:** https://github.com/FFmpeg/FFmpeg/tree/n{{FFMPEG_VERSION}}
- **Trademark policy:** https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **Files:** `bin/flac`
- **Version:** {{FLAC_VERSION}}
- **License:** BSD-3-Clause
- **Source:** https://ftp.osuosl.org/pub/xiph/releases/flac/flac-{{FLAC_VERSION}}.tar.xz

---

## fdkaac (command-line encoder) + FDK-AAC (library)

### fdkaac

- **Files:** `bin/fdkaac`
- **Version:** v{{FDKAAC_VERSION}}
- **License:** Zlib, with additional notices in upstream `COPYING`.
- **Source:** https://github.com/nu774/fdkaac/tree/v{{FDKAAC_VERSION}}
- **License text:** https://raw.githubusercontent.com/nu774/fdkaac/v{{FDKAAC_VERSION}}/COPYING

### Fraunhofer FDK AAC Codec Library

- **Files:** `lib/libfdk-aac.2.dylib`, loaded by `fdkaac`
- **Version:** v{{FDK_AAC_VERSION}}
- **License:** Fraunhofer Software License for the FDK AAC Codec Library for Android.
- **Source:** https://github.com/mstorsjo/fdk-aac/tree/v{{FDK_AAC_VERSION}}
- **License text:** https://raw.githubusercontent.com/mstorsjo/fdk-aac/v{{FDK_AAC_VERSION}}/NOTICE

---

## x264

- **Files:** `bin/x264`
- **Version:** `{{X264_VERSION}}`
- **License:** GPL-2.0-or-later
- **Source:** https://code.videolan.org/videolan/x264

---

## x265

- **Files:** `bin/x265`
- **Version:** {{X265_VERSION}}
- **License:** GPL-2.0
- **Source:** https://github.com/Multicorewareinc/x265/tree/{{X265_VERSION}}

---

## SVT-AV1 (SvtAv1EncApp)

- **Files:** `bin/SvtAv1EncApp`
- **Version:** v{{SVT_AV1_VERSION}}
- **License:** BSD-3-Clause
- **Source:** https://gitlab.com/AOMediaCodec/SVT-AV1/-/tree/v{{SVT_AV1_VERSION}}

---

## tsMuxeR

- **Files:** `bin/tsMuxeR`
- **Version:** v{{TSMUXER_VERSION}}
- **License:** Apache-2.0
- **Source:** https://github.com/justdan96/tsMuxer/tree/{{TSMUXER_VERSION}}

---

## dovi_tool

- **Files:** `bin/dovi_tool`
- **Version:** {{DOVI_TOOL_VERSION}}
- **License:** MIT
- **Source:** https://github.com/quietvoid/dovi_tool/tree/{{DOVI_TOOL_VERSION}}

---

## hdr10plus_tool

- **Files:** `bin/hdr10plus_tool`
- **Version:** {{HDR10PLUS_TOOL_VERSION}}
- **License:** MIT
- **Source:** https://github.com/quietvoid/hdr10plus_tool/tree/{{HDR10PLUS_TOOL_VERSION}}

---

## libass

- **Files:** `lib/libass.9.dylib`
- **Version:** {{LIBASS_VERSION}}
- **License:** ISC
- **Source:** https://github.com/libass/libass/tree/{{LIBASS_VERSION}}

---

## MKVToolNix

- **Files:** `bin/mkvmerge`, `mkvextract`, `mkvinfo`, `mkvpropedit`
- **Version:** v{{MKVTOOLNIX_VERSION}}
- **License:** GPL-2.0
- **Source:** https://codeberg.org/mbunkus/mkvtoolnix/archive/release-{{MKVTOOLNIX_VERSION}}.zip
- **License text:** https://codeberg.org/mbunkus/mkvtoolnix/raw/branch/main/COPYING

---

## Shared VapourSynth and Python runtime

The application and VSScript share the CPython runtime and NumPy package in `Contents/Resources/Runtime/`.

### VapourSynth

- **Files:** `{{SITE_PACKAGES}}/vapoursynth/` including the core, the Python module, VSScript and VSPipe
- **Version:** {{VAPOURSYNTH_VERSION}}
- **License:** LGPL-2.1-or-later
- **Source:** https://github.com/vapoursynth/vapoursynth/tree/{{VAPOURSYNTH_VERSION}}
- **Bundled license text:** [COPYING.LESSER](vapoursynth/COPYING.LESSER)

### CPython

- **Files:** `python/lib/libpython.dylib` and `python/`
- **Version:** {{PYTHON_VERSION}} ({{PYTHON_ARCHITECTURE}})
- **License:** PSF-2.0
- **Source:** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/Python-{{PYTHON_VERSION}}.tgz
- **License text:** [CPython-LICENSE.txt](CPython-LICENSE.txt)

### NumPy

- **Files:** `{{SITE_PACKAGES}}/numpy/` and its bundled native libraries
- **Version:** {{NUMPY_VERSION}}
- **License:** BSD-3-Clause
- **Source:** https://github.com/numpy/numpy/tree/v{{NUMPY_VERSION}}
- **Bundled license texts:** `{{SITE_PACKAGES}}/numpy-{{NUMPY_VERSION}}.dist-info/licenses/`

### VapourSynth Python filter scripts

The Python modules shipped next to the shared runtime retain their upstream notices and licenses.
- **Copyright, sources and licenses:** [COPYRIGHT.md](vapoursynth_scripts/COPYRIGHT.md)
- **Bundled license texts:** `legal/vapoursynth_scripts/licenses/`

### Native filter plugins

The table lists the native filters in this build. Versions come from the installation record or the registered plugin version.

| Component | Version / revision | Bundled file | Upstream and license |
| --- | --- | --- | --- |
{{VAPOURSYNTH_COMPONENTS}}

ZNEDI3 includes the [plugin, GraphEngine, and VSXX licenses](znedi3/).

---

## VapourSynth Editor

- **Files:** `bin/vsedit`
- **Version:** {{VSEDIT_VERSION}}
- **License:** MIT
- **Source:** https://github.com/YomikoR/VapourSynth-Editor/tree/{{VSEDIT_VERSION}}

---

## Qt and PyQt6

### Qt

- **Files:** Qt libraries and platform plugins for both variants under `qt/`.
- **Version:** {{QT_VERSION}} / 6.6.3
- **License:** Open-source Qt terms, including LGPL-3.0 for the library modules that offer that option. See each module’s upstream notices.
- **Source:** https://code.qt.io/cgit/qt/qtbase.git/tag/?h=v{{QT_VERSION}}
- **License terms:** https://doc.qt.io/qt-6/licensing.html

### PyQt6

- **Files:** `qt/*/PyQt6/` Python bindings
- **Version:** {{PYQT_VERSION}} / 6.6.1
- **License:** GPL-3.0
- **Source:** https://www.riverbankcomputing.com/software/pyqt/download

---

## SoundFile and libsndfile

### SoundFile

- **Files:** SoundFile Python module
- **Version:** {{SOUNDFILE_VERSION}}
- **License:** BSD-3-Clause
- **Source:** https://github.com/bastibe/python-soundfile

### libsndfile

- **Files:** The shared libsndfile loaded by SoundFile for PCM bit-depth detection.
- **Version:** {{LIBSNDFILE_VERSION}}
- **License:** LGPL-2.1-or-later
- **Source:** https://github.com/libsndfile/libsndfile/tree/{{LIBSNDFILE_VERSION}}

---

## Pillow and pycountry

### Pillow

- **Files:** `PIL/` image library
- **Version:** {{PILLOW_VERSION}}
- **License:** HPND
- **Source:** https://github.com/python-pillow/Pillow/tree/{{PILLOW_VERSION}}

### pycountry

- **Files:** pycountry and the ISO datasets in `pycountry/databases/`
- **Version:** {{PYCOUNTRY_VERSION}}
- **License:** LGPL-2.1-or-later; see the upstream notices for the datasets.
- **Source:** https://github.com/pycountry/pycountry

---

## Additional bundled libraries

| Component | Version / revision | Source and license |
| --- | --- | --- |
{{ADDITIONAL_COMPONENTS}}
