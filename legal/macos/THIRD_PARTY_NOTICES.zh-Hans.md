# 第三方许可声明（随附二进制文件）

**产品：** BluraySubtitle（macOS，{{PYTHON_ARCHITECTURE}}）

BluraySubtitle 版权所有 © 2024 Haruite，以 [MIT 许可证](BluraySubtitle-LICENSE.txt)分发。下列路径以应用内的 `Contents/Resources/Runtime/` 为基准。

---

## 7-Zip

- **文件：** `bin/7zz`
- **版本：** {{SEVEN_ZIP_VERSION}}
- **许可证：** GNU LGPL，部分代码采用 BSD-3-Clause，并包含 unRAR 限制
- **源码：** https://github.com/ip7z/7zip/tree/{{SEVEN_ZIP_VERSION}}
- **许可原文：** https://www.7-zip.org/license.txt

---

## FFmpeg / FFprobe

- **文件：** `bin/ffmpeg`, `bin/ffprobe`
- **版本：** `ffmpeg-{{FFMPEG_VERSION}}`
- **许可证：** 本构建使用 LGPL-2.1-or-later，随包程序的 `-L` 选项可显示许可声明。
- **源码：** https://github.com/FFmpeg/FFmpeg/tree/n{{FFMPEG_VERSION}}
- **商标政策：** https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **文件：** `bin/flac`
- **版本：** {{FLAC_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://ftp.osuosl.org/pub/xiph/releases/flac/flac-{{FLAC_VERSION}}.tar.xz

---

## fdkaac（命令行编码器）+ FDK-AAC（库）

### fdkaac

- **文件：** `bin/fdkaac`
- **版本：** v{{FDKAAC_VERSION}}
- **许可证：** Zlib，附加许可说明见上游 `COPYING`。
- **源码：** https://github.com/nu774/fdkaac/tree/v{{FDKAAC_VERSION}}
- **许可原文：** https://raw.githubusercontent.com/nu774/fdkaac/v{{FDKAAC_VERSION}}/COPYING

### Fraunhofer FDK AAC Codec Library

- **文件：** `fdkaac` 加载的 `lib/libfdk-aac.2.dylib`
- **版本：** v{{FDK_AAC_VERSION}}
- **许可证：** Fraunhofer FDK AAC Codec Library for Android 软件许可证。
- **源码：** https://github.com/mstorsjo/fdk-aac/tree/v{{FDK_AAC_VERSION}}
- **许可原文：** https://raw.githubusercontent.com/mstorsjo/fdk-aac/v{{FDK_AAC_VERSION}}/NOTICE

---

## x264

- **文件：** `bin/x264`
- **版本：** `{{X264_VERSION}}`
- **许可证：** GPL-2.0-or-later
- **源码：** https://code.videolan.org/videolan/x264

---

## x265

- **文件：** `bin/x265`
- **版本：** {{X265_VERSION}}
- **许可证：** GPL-2.0
- **源码：** https://github.com/Multicorewareinc/x265/tree/{{X265_VERSION}}

---

## SVT-AV1（SvtAv1EncApp）

- **文件：** `bin/SvtAv1EncApp`
- **版本：** v{{SVT_AV1_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://gitlab.com/AOMediaCodec/SVT-AV1/-/tree/v{{SVT_AV1_VERSION}}

---

## tsMuxeR

- **文件：** `bin/tsMuxeR`
- **版本：** v{{TSMUXER_VERSION}}
- **许可证：** Apache-2.0
- **源码：** https://github.com/justdan96/tsMuxer/tree/{{TSMUXER_VERSION}}

---

## dovi_tool

- **文件：** `bin/dovi_tool`
- **版本：** {{DOVI_TOOL_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/quietvoid/dovi_tool/tree/{{DOVI_TOOL_VERSION}}

---

## hdr10plus_tool

- **文件：** `bin/hdr10plus_tool`
- **版本：** {{HDR10PLUS_TOOL_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/quietvoid/hdr10plus_tool/tree/{{HDR10PLUS_TOOL_VERSION}}

---

## libass

- **文件：** `lib/libass.9.dylib`
- **版本：** {{LIBASS_VERSION}}
- **许可证：** ISC
- **源码：** https://github.com/libass/libass/tree/{{LIBASS_VERSION}}

---

## MKVToolNix

- **文件：** `bin/mkvmerge`, `mkvextract`, `mkvinfo`, `mkvpropedit`
- **版本：** v{{MKVTOOLNIX_VERSION}}
- **许可证：** GPL-2.0
- **源码：** https://codeberg.org/mbunkus/mkvtoolnix/archive/release-{{MKVTOOLNIX_VERSION}}.zip
- **许可原文：** https://codeberg.org/mbunkus/mkvtoolnix/raw/branch/main/COPYING

---

## VapourSynth 与 Python 共享运行时

应用与 VSScript 共用 `Contents/Resources/Runtime/` 中的 CPython 运行时和 NumPy 包。

### VapourSynth

- **文件：** `{{SITE_PACKAGES}}/vapoursynth/` 中的核心库、Python 模块、VSScript 和 VSPipe
- **版本：** {{VAPOURSYNTH_VERSION}}
- **许可证：** LGPL-2.1-or-later
- **源码：** https://github.com/vapoursynth/vapoursynth/tree/{{VAPOURSYNTH_VERSION}}
- **随附许可原文：** [COPYING.LESSER](vapoursynth/COPYING.LESSER)

### CPython

- **文件：** `python/lib/libpython.dylib` 与 `python/`
- **版本：** {{PYTHON_VERSION}}（{{PYTHON_ARCHITECTURE}}）
- **许可证：** PSF-2.0
- **源码：** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/Python-{{PYTHON_VERSION}}.tgz
- **许可原文：** [CPython-LICENSE.txt](CPython-LICENSE.txt)

### NumPy

- **文件：** `{{SITE_PACKAGES}}/numpy/` 和随附的原生库
- **版本：** {{NUMPY_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://github.com/numpy/numpy/tree/v{{NUMPY_VERSION}}
- **随附许可原文：** `{{SITE_PACKAGES}}/numpy-{{NUMPY_VERSION}}.dist-info/licenses/`

### VapourSynth Python 滤镜脚本

与共享运行时一同提供的 Python 模块保留各自的上游声明和许可。
- **版权、来源与许可：** [COPYRIGHT.md](vapoursynth_scripts/COPYRIGHT.md)
- **随附许可原文：** `legal/vapoursynth_scripts/licenses/`

### 原生滤镜插件

下表列出本次构建实际收录的原生滤镜。版本来自安装记录或插件注册信息。

| 组件 | 版本／修订 | 随附文件 | 上游与许可 |
| --- | --- | --- | --- |
{{VAPOURSYNTH_COMPONENTS}}

ZNEDI3 随附[插件本身及 GraphEngine、VSXX 的许可原文](znedi3/)。

---

## VapourSynth Editor

- **文件：** `bin/vsedit`
- **版本：** {{VSEDIT_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/YomikoR/VapourSynth-Editor/tree/{{VSEDIT_VERSION}}

---

## Qt 与 PyQt6

### Qt

- **文件：** 位于 `qt/` 中的两套 Qt 共享库和平台插件。
- **版本：** {{QT_VERSION}} / 6.6.3
- **许可证：** Qt 的开源许可，其中提供该选项的库模块采用 LGPL-3.0。详情见各模块的上游声明。
- **源码：** https://code.qt.io/cgit/qt/qtbase.git/tag/?h=v{{QT_VERSION}}
- **许可条款：** https://doc.qt.io/qt-6/licensing.html

### PyQt6

- **文件：** `qt/*/PyQt6/` 中的 Python 绑定
- **版本：** {{PYQT_VERSION}} / 6.6.1
- **许可证：** GPL-3.0
- **源码：** https://www.riverbankcomputing.com/software/pyqt/download

---

## SoundFile 与 libsndfile

### SoundFile

- **文件：** SoundFile Python 模块
- **版本：** {{SOUNDFILE_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://github.com/bastibe/python-soundfile

### libsndfile

- **文件：** SoundFile 用于检测 PCM 位深的 libsndfile 共享库。
- **版本：** {{LIBSNDFILE_VERSION}}
- **许可证：** LGPL-2.1-or-later
- **源码：** https://github.com/libsndfile/libsndfile/tree/{{LIBSNDFILE_VERSION}}

---

## Pillow 与 pycountry

### Pillow

- **文件：** `PIL/` 图像库
- **版本：** {{PILLOW_VERSION}}
- **许可证：** HPND
- **源码：** https://github.com/python-pillow/Pillow/tree/{{PILLOW_VERSION}}

### pycountry

- **文件：** pycountry 和 `pycountry/databases/` 中的 ISO 数据集
- **版本：** {{PYCOUNTRY_VERSION}}
- **许可证：** LGPL-2.1-or-later，数据集许可见上游声明。
- **源码：** https://github.com/pycountry/pycountry

---

## 其他随附库

| 组件 | 版本／修订 | 源码与许可 |
| --- | --- | --- |
{{ADDITIONAL_COMPONENTS}}
