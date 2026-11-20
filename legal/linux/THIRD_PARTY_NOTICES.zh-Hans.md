# 第三方许可声明（随附二进制文件）

**产品：** BluraySubtitle（Linux，PyInstaller 单目录构建）

运行 `tools/build_linux_package.sh` 时，会根据所选的随附组件更新版本字段。

---

## 7-Zip

- **文件：** `linux/libexec/7zz`
- **版本：** {{SEVEN_ZIP_VERSION}}
- **许可证：** GNU LGPL，部分代码采用 BSD-3-Clause，并包含 unRAR 限制
- **源码：** https://github.com/ip7z/7zip/tree/{{SEVEN_ZIP_VERSION}}
- **许可原文：** https://www.7-zip.org/license.txt

---

## FFmpeg / FFprobe

- **文件：** `linux/libexec/ffmpeg`, `linux/libexec/ffprobe`
- **版本：** `ffmpeg-{{FFMPEG_BUILD}}`
- **许可证：** 本次构建采用 GPL-2.0-or-later，具体许可见程序的 `-L` 输出。
- **源码：** https://github.com/FFmpeg/FFmpeg/tree/n{{FFMPEG_VERSION}}
- **商标政策：** https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **文件：** `linux/libexec/flac` 与 libFLAC 共享库
- **版本：** {{FLAC_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://ftp.osuosl.org/pub/xiph/releases/flac/flac-{{FLAC_VERSION}}.tar.xz

---

## fdkaac（命令行编码器）+ FDK-AAC（库）

### fdkaac

- **文件：** `linux/libexec/fdkaac`
- **版本：** v{{FDKAAC_VERSION}}
- **许可证：** Zlib，附加许可说明见上游 `COPYING`。
- **源码：** https://github.com/nu774/fdkaac/tree/v{{FDKAAC_VERSION}}
- **许可原文：** https://raw.githubusercontent.com/nu774/fdkaac/v{{FDKAAC_VERSION}}/COPYING

### Fraunhofer FDK AAC Codec Library

- **文件：** `fdkaac` 加载的 `libfdk-aac.so.2`
- **版本：** v{{FDK_AAC_VERSION}}
- **许可证：** Fraunhofer FDK AAC Codec Library for Android 软件许可证。
- **源码：** https://github.com/mstorsjo/fdk-aac/tree/v{{FDK_AAC_VERSION}}
- **许可原文：** https://raw.githubusercontent.com/mstorsjo/fdk-aac/v{{FDK_AAC_VERSION}}/NOTICE

---

## x264

- **文件：** `linux/libexec/x264`
- **版本：** `{{X264_VERSION}}`
- **许可证：** GPL-2.0-or-later
- **源码：** https://code.videolan.org/videolan/x264

---

## x265

- **文件：** `linux/libexec/x265`
- **版本：** {{X265_VERSION}}
- **许可证：** GPL-2.0
- **源码：** https://github.com/Multicorewareinc/x265/tree/{{X265_VERSION}}

---

## SVT-AV1（SvtAv1EncApp）

- **文件：** `linux/libexec/SvtAv1EncApp`
- **版本：** v{{SVT_AV1_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://gitlab.com/AOMediaCodec/SVT-AV1/-/tree/v{{SVT_AV1_VERSION}}

---

## tsMuxeR

- **文件：** `linux/libexec/tsMuxeR`
- **版本：** v{{TSMUXER_VERSION}}
- **许可证：** Apache-2.0
- **源码：** https://github.com/justdan96/tsMuxer/tree/{{TSMUXER_VERSION}}

---

## dovi_tool

- **文件：** `linux/libexec/dovi_tool`
- **版本：** {{DOVI_TOOL_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/quietvoid/dovi_tool/tree/{{DOVI_TOOL_VERSION}}

---

## hdr10plus_tool

- **文件：** `linux/libexec/hdr10plus_tool`
- **版本：** {{HDR10PLUS_TOOL_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/quietvoid/hdr10plus_tool/tree/{{HDR10PLUS_TOOL_VERSION}}

---

## libass

- **文件：** `libass.so.9`
- **版本：** {{LIBASS_VERSION}}
- **许可证：** ISC
- **源码：** https://github.com/libass/libass/tree/{{LIBASS_VERSION}}

---

## MKVToolNix

- **文件：** `linux/libexec/mkvmerge`, `mkvextract`, `mkvinfo`, `mkvpropedit`
- **版本：** v{{MKVTOOLNIX_VERSION}}
- **许可证：** GPL-2.0
- **源码：** https://codeberg.org/mbunkus/mkvtoolnix/archive/release-{{MKVTOOLNIX_VERSION}}.zip
- **许可原文：** https://codeberg.org/mbunkus/mkvtoolnix/raw/branch/main/COPYING

---

## mpv

- **文件：** `linux/libexec/mpv` 与 `resource/mpv/` 中的右键菜单
- **版本：** {{MPV_VERSION}}
- **许可证：** GPL-2.0-or-later。其他许可的组件见上游 Copyright 文件。
- **源码：** https://github.com/mpv-player/mpv
- **许可原文：** https://github.com/mpv-player/mpv/blob/master/Copyright

---

## uosc

- {{UOSC_VERSION}} 版包含 `resource/mpv/scripts/uosc/` 和 `resource/mpv/fonts/`。[上游源码](https://github.com/tomasklaen/uosc)
- 按 LGPL-2.1 分发。[随附许可原文](uosc/LICENSE.LGPL)

## mpv-lazy 着色器

- 程序包包含 mpv-lazy 2026FM 的着色器源码。[来源和许可](mpv_lazy_shaders/COPYRIGHT.zh-Hans.md)

---

## VapourSynth 与 Python 共享运行时

应用与 VSScript 共用 `_internal/` 中的 CPython 运行时和 NumPy 包。

### VapourSynth

- **文件：** `vapoursynth/` 中的核心库、Python 模块、VSScript 和 VSPipe
- **版本：** {{VAPOURSYNTH_VERSION}}
- **许可证：** LGPL-2.1-or-later
- **源码：** https://github.com/vapoursynth/vapoursynth/tree/{{VAPOURSYNTH_VERSION}}
- **随附许可原文：** [COPYING.LESSER](vapoursynth/COPYING.LESSER)

### CPython

- **文件：** `{{PYTHON_LIBRARY}}` 与 `linux/python/`
- **版本：** {{PYTHON_VERSION}}（{{PYTHON_ARCHITECTURE}}）
- **许可证：** PSF-2.0
- **源码：** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/Python-{{PYTHON_VERSION}}.tgz
- **许可原文：** [CPython-LICENSE.txt](CPython-LICENSE.txt)

### GNU C Library

- **版本：** {{GLIBC_VERSION}}
- **文件：** `linux/glibc/`，包括对应架构的动态加载器。
- **随附版权和许可：** [glibc-copyright](glibc-copyright)

### 图形客户端库

包内包含 OpenGL、DRM、VA-API、VDPAU 和 Vulkan 客户端库，随附 [libglvnd](libglvnd0-copyright)、[libdrm](libdrm2-copyright)、[libva](libva2-copyright)、[libvdpau](libvdpau1-copyright) 和 [Vulkan 加载器](libvulkan1-copyright)的版权与许可文本。

### NumPy

- **文件：** `numpy/` 和随附的原生库
- **版本：** {{NUMPY_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://github.com/numpy/numpy/tree/v{{NUMPY_VERSION}}
- **随附许可原文：** `numpy-{{NUMPY_VERSION}}.dist-info/licenses/`

### VapourSynth Python 滤镜脚本

与共享运行时一同提供的 Python 模块保留各自的上游声明和许可。
- **版权、来源与许可：** [COPYRIGHT.md](vapoursynth_scripts/COPYRIGHT.md)
- **随附许可原文：** `legal/vapoursynth_scripts/licenses/`

### 原生滤镜插件

下表列出本次构建实际收录的原生滤镜。版本来自安装记录或插件注册信息。

| 组件 | 版本／修订 | 随附文件 | 上游与许可 |
| --- | --- | --- | --- |
{{VAPOURSYNTH_COMPONENTS}}

ZNEDI3 随附[插件本身及 GraphEngine、VSXX 的许可原文](vapoursynth/components/znedi3/)。

---

## VapourSynth Editor

- **文件：** `linux/libexec/vsedit`
- **版本：** {{VSEDIT_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/YomikoR/VapourSynth-Editor/tree/{{VSEDIT_VERSION}}

---

## Qt 与 PyQt6

### Qt

- **文件：** 位于 `linux/qt/` 中的两套 Qt 共享库和平台插件。
- **版本：** {{QT_VERSION}} / 6.6.3
- **许可证：** Qt 的开源许可，其中提供该选项的库模块采用 LGPL-3.0。详情见各模块的上游声明。
- **源码：** https://code.qt.io/cgit/qt/qtbase.git/tag/?h=v{{QT_VERSION}}
- **许可条款：** https://doc.qt.io/qt-6/licensing.html

### PyQt6

- **文件：** `linux/qt/*/PyQt6/` 中的 Python 绑定
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

## PyInstaller 运行时

- **文件：** 单目录包中的引导加载程序与冻结的 Python 运行时。
- **版本：** {{PYINSTALLER_VERSION}}
- **许可证：** GPL-2.0-or-later，含 PyInstaller 引导加载程序例外。
- **源码：** https://github.com/pyinstaller/pyinstaller/releases/tag/v{{PYINSTALLER_VERSION}}
- **许可原文：** https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

---
