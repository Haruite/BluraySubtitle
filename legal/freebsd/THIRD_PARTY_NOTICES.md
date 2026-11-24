# Third-party notices (bundled binaries)

**Product** BluraySubtitle (FreeBSD amd64, built on {{FREEBSD_VERSION}})

BluraySubtitle is distributed under the [MIT License](LICENSE). File paths below start at `_internal/`. Versions and sources reflect the components selected for the build.

---

## 7-Zip

- **Files** `libexec/7zz`
- **Version** {{SEVEN_ZIP_VERSION}}
- **License** {{SEVEN_ZIP_LICENSE}}
- **Source** {{SEVEN_ZIP_SOURCE}}
- **License text** {{SEVEN_ZIP_LICENSE_FILES}}

---

## FFmpeg / FFprobe

- **Files** `libexec/ffmpeg`, `libexec/ffprobe` and the FFmpeg shared libraries
- **Version** {{FFMPEG_VERSION}}
- **License** {{FFMPEG_LICENSE}}. Run `ffmpeg -L` for the terms of this build.
- **Source** {{FFMPEG_SOURCE}}
- **License text** {{FFMPEG_LICENSE_FILES}}
- **Trademark policy** https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **Files** `libexec/flac` and the shared libFLAC
- **Version** {{FLAC_VERSION}}
- **License** {{FLAC_LICENSE}}
- **Source** {{FLAC_SOURCE}}
- **License text** {{FLAC_LICENSE_FILES}}

---

## fdkaac (command-line encoder) + FDK-AAC (library)

### fdkaac

- **Files** `libexec/fdkaac`
- **Version** {{FDKAAC_VERSION}}
- **License** Zlib, with additional notices in [COPYING](fdkaac/COPYING).
- **Source** {{FDKAAC_SOURCE}}

### Fraunhofer FDK AAC Codec Library

- **Files** The shared libfdk-aac loaded by fdkaac
- **Version** {{FDK_AAC_VERSION}}
- **License** {{FDK_AAC_LICENSE}}
- **Source** {{FDK_AAC_SOURCE}}
- **License text** {{FDK_AAC_LICENSE_FILES}}

---

## x264

- **Files** `libexec/x264`
- **Version** {{X264_VERSION}}
- **License** {{X264_LICENSE}}
- **Source** {{X264_SOURCE}}
- **License text** {{X264_LICENSE_FILES}}

---

## x265

- **Files** `libexec/x265` and the shared libx265
- **Version** {{X265_VERSION}}
- **License** {{X265_LICENSE}}
- **Source** {{X265_SOURCE}}
- **License text** {{X265_LICENSE_FILES}}

---

## SVT-AV1 (SvtAv1EncApp)

- **Files** `libexec/SvtAv1EncApp` and the shared SVT-AV1 encoder library
- **Version** {{SVT_AV1_VERSION}}
- **License** {{SVT_AV1_LICENSE}}
- **Source** {{SVT_AV1_SOURCE}}
- **License text** {{SVT_AV1_LICENSE_FILES}}

---

## tsMuxeR

- **Files** `libexec/tsMuxeR`
- **Version** {{TSMUXER_VERSION}}
- **License** [Apache-2.0](tsmuxer/LICENSE)
- **Source** {{TSMUXER_SOURCE}}

---

## dovi_tool

- **Files** `libexec/dovi_tool`
- **Version** {{DOVI_TOOL_VERSION}}
- **License** {{DOVI_TOOL_LICENSE}}
- **Source** {{DOVI_TOOL_SOURCE}}
- **License text** {{DOVI_TOOL_LICENSE_FILES}}

---

## hdr10plus_tool

- **Files** `libexec/hdr10plus_tool`
- **Version** {{HDR10PLUS_TOOL_VERSION}}
- **License** [MIT](hdr10plus_tool/LICENSE)
- **Source** {{HDR10PLUS_TOOL_SOURCE}}

---

## libass

- **Files** Shared libass in `lib/`
- **Version** {{LIBASS_VERSION}}
- **License** {{LIBASS_LICENSE}}
- **Source** {{LIBASS_SOURCE}}
- **License text** {{LIBASS_LICENSE_FILES}}

---

## MKVToolNix

- **Files** `libexec/mkvmerge`, `libexec/mkvextract`, `libexec/mkvinfo`, `libexec/mkvpropedit`
- **Version** {{MKVTOOLNIX_VERSION}}
- **License** {{MKVTOOLNIX_LICENSE}}
- **Source** {{MKVTOOLNIX_SOURCE}}
- **License text** {{MKVTOOLNIX_LICENSE_FILES}}

---

## mpv

- **Files** `libexec/mpv` and the context menus in `mpv/`
- **Version** {{MPV_VERSION}}
- **License** [GPL-2.0-or-later](mpv/LICENSE.GPL), with portions under the [LGPL](mpv/LICENSE.LGPL).
- **Source** {{MPV_SOURCE}}

### libplacebo renderer

- **Files** libplacebo linked into `libexec/mpv`
- **Version** {{LIBPLACEBO_MPV_VERSION}}
- **License** [Bundled license and dependency notices](libplacebo-mpv/LICENSE)
- **Source** {{LIBPLACEBO_MPV_SOURCE}}

---

## uosc

- **Files** `mpv/scripts/uosc/`, including the native Ziggy helper, and the uosc fonts in `mpv/fonts/`
- **Version** {{UOSC_VERSION}}
- **License** [LGPL-2.1](uosc/LICENSE.LGPL). Ziggy dependencies have notices under `legal/uosc/`.
- **Source** {{UOSC_SOURCE}}

## mpv-lazy shaders

The bundled playback profiles and shaders include their [source and license notices](mpv_lazy_shaders/COPYRIGHT.md).

---

## Shared VapourSynth and Python runtime

The application and VSScript share CPython and NumPy in `python/`.

### VapourSynth

- **Files** `{{SITE_PACKAGES}}/vapoursynth/`, including the core, Python module, VSScript and VSPipe
- **Version** {{VAPOURSYNTH_VERSION}}
- **License** [LGPL-2.1-or-later](vapoursynth/COPYING.LESSER)
- **Source** {{VAPOURSYNTH_SOURCE}}

### CPython

- **Files** The interpreter and standard library in `python/`
- **Version** {{PYTHON_VERSION}}
- **License** {{PYTHON_LICENSE}}
- **Source** {{PYTHON_SOURCE}}
- **License text** {{PYTHON_LICENSE_FILES}}

### NumPy

- **Files** `{{SITE_PACKAGES}}/numpy/` and its bundled native libraries
- **Version** {{NUMPY_VERSION}}
- **License** {{NUMPY_LICENSE}}
- **Source** {{NUMPY_SOURCE}}
- **License text** {{NUMPY_LICENSE_FILES}}

### VapourSynth Python filter scripts

The bundled scripts retain their [copyright, sources and licenses](vapoursynth_scripts/COPYRIGHT.md). License texts are under `legal/vapoursynth_scripts/licenses/`.

### Native filter plugins

The native filters in `plugins/` use the sources and revisions listed below.

| Component | Version / revision | Source | Bundled license files |
| --- | --- | --- | --- |
{{VAPOURSYNTH_COMPONENTS}}

---

## VapourSynth Editor

- **Files** `libexec/vsedit`
- **Version** {{VSEDIT_VERSION}}
- **License** [MIT](vsedit/LICENSE)
- **Source** {{VSEDIT_SOURCE}}

---

## Qt and PyQt6

### Qt

- **Files** Qt libraries in `lib/`, with plugins and translations in `qt/`
- **Version** {{QT_VERSION}}
- **License** [Qt open-source terms](https://doc.qt.io/qt-6/licensing.html). See the license notices for the individual modules.
- **Source** {{QT_SOURCE}}
- **License text** {{QT_LICENSE_FILES}}

### PyQt6

- **Files** `{{SITE_PACKAGES}}/PyQt6/` Python bindings
- **Version** {{PYQT_VERSION}}
- **License** {{PYQT_LICENSE}}
- **Source** {{PYQT_SOURCE}}
- **License text** {{PYQT_LICENSE_FILES}}

---

## SoundFile and libsndfile

### SoundFile

- **Files** The SoundFile Python module
- **Version** {{SOUNDFILE_VERSION}}
- **License** {{SOUNDFILE_LICENSE}}
- **Source** {{SOUNDFILE_SOURCE}}
- **License text** {{SOUNDFILE_LICENSE_FILES}}

### libsndfile

- **Files** `lib/libsndfile.so.1`
- **Version** {{LIBSNDFILE_VERSION}}
- **License** {{LIBSNDFILE_LICENSE}}
- **Source** {{LIBSNDFILE_SOURCE}}
- **License text** {{LIBSNDFILE_LICENSE_FILES}}

---

## Pillow and pycountry

### Pillow

- **Files** `{{SITE_PACKAGES}}/PIL/`
- **Version** {{PILLOW_VERSION}}
- **License** {{PILLOW_LICENSE}}
- **Source** {{PILLOW_SOURCE}}
- **License text** {{PILLOW_LICENSE_FILES}}

### pycountry

- **Files** `{{SITE_PACKAGES}}/pycountry/` and its ISO datasets
- **Version** {{PYCOUNTRY_VERSION}}
- **License** {{PYCOUNTRY_LICENSE}}
- **Source** {{PYCOUNTRY_SOURCE}}
- **License text** {{PYCOUNTRY_LICENSE_FILES}}

---

## Additional bundled libraries

The table lists additional libraries with the license declarations published by FreeBSD Ports. License files supplied by the ports are collected under `legal/ports/`. License texts for the bundled FreeBSD base libraries are under `legal/freebsd-base/`.

| Component | Version | License | Source |
| --- | --- | --- | --- |
{{ADDITIONAL_COMPONENTS}}
