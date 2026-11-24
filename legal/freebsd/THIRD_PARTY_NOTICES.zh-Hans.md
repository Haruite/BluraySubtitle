# 第三方许可声明（随附二进制文件）

**产品** BluraySubtitle（FreeBSD amd64，构建系统为 {{FREEBSD_VERSION}}）

BluraySubtitle 按 [MIT 许可证](LICENSE) 分发。下文文件路径均相对于 `_internal/`。版本和源码对应构建时选用的组件。

---

## 7-Zip

- **文件** `libexec/7zz`
- **版本** {{SEVEN_ZIP_VERSION}}
- **许可证** {{SEVEN_ZIP_LICENSE}}
- **源码** {{SEVEN_ZIP_SOURCE}}
- **许可原文** {{SEVEN_ZIP_LICENSE_FILES}}

---

## FFmpeg / FFprobe

- **文件** `libexec/ffmpeg`、`libexec/ffprobe` 及 FFmpeg 共享库
- **版本** {{FFMPEG_VERSION}}
- **许可证** {{FFMPEG_LICENSE}}。可用 `ffmpeg -L` 查看当前构建的许可条款。
- **源码** {{FFMPEG_SOURCE}}
- **许可原文** {{FFMPEG_LICENSE_FILES}}
- **商标政策** https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **文件** `libexec/flac` 及 libFLAC 共享库
- **版本** {{FLAC_VERSION}}
- **许可证** {{FLAC_LICENSE}}
- **源码** {{FLAC_SOURCE}}
- **许可原文** {{FLAC_LICENSE_FILES}}

---

## fdkaac（命令行编码器）+ FDK-AAC（库）

### fdkaac

- **文件** `libexec/fdkaac`
- **版本** {{FDKAAC_VERSION}}
- **许可证** Zlib。附加声明见 [COPYING](fdkaac/COPYING)。
- **源码** {{FDKAAC_SOURCE}}

### Fraunhofer FDK AAC Codec Library

- **文件** fdkaac 加载的 libfdk-aac 共享库
- **版本** {{FDK_AAC_VERSION}}
- **许可证** {{FDK_AAC_LICENSE}}
- **源码** {{FDK_AAC_SOURCE}}
- **许可原文** {{FDK_AAC_LICENSE_FILES}}

---

## x264

- **文件** `libexec/x264`
- **版本** {{X264_VERSION}}
- **许可证** {{X264_LICENSE}}
- **源码** {{X264_SOURCE}}
- **许可原文** {{X264_LICENSE_FILES}}

---

## x265

- **文件** `libexec/x265` 及 libx265 共享库
- **版本** {{X265_VERSION}}
- **许可证** {{X265_LICENSE}}
- **源码** {{X265_SOURCE}}
- **许可原文** {{X265_LICENSE_FILES}}

---

## SVT-AV1（SvtAv1EncApp）

- **文件** `libexec/SvtAv1EncApp` 及 SVT-AV1 编码器共享库
- **版本** {{SVT_AV1_VERSION}}
- **许可证** {{SVT_AV1_LICENSE}}
- **源码** {{SVT_AV1_SOURCE}}
- **许可原文** {{SVT_AV1_LICENSE_FILES}}

---

## tsMuxeR

- **文件** `libexec/tsMuxeR`
- **版本** {{TSMUXER_VERSION}}
- **许可证** [Apache-2.0](tsmuxer/LICENSE)
- **源码** {{TSMUXER_SOURCE}}

---

## dovi_tool

- **文件** `libexec/dovi_tool`
- **版本** {{DOVI_TOOL_VERSION}}
- **许可证** {{DOVI_TOOL_LICENSE}}
- **源码** {{DOVI_TOOL_SOURCE}}
- **许可原文** {{DOVI_TOOL_LICENSE_FILES}}

---

## hdr10plus_tool

- **文件** `libexec/hdr10plus_tool`
- **版本** {{HDR10PLUS_TOOL_VERSION}}
- **许可证** [MIT](hdr10plus_tool/LICENSE)
- **源码** {{HDR10PLUS_TOOL_SOURCE}}

---

## libass

- **文件** `lib/` 中的 libass 共享库
- **版本** {{LIBASS_VERSION}}
- **许可证** {{LIBASS_LICENSE}}
- **源码** {{LIBASS_SOURCE}}
- **许可原文** {{LIBASS_LICENSE_FILES}}

---

## MKVToolNix

- **文件** `libexec/mkvmerge`、`libexec/mkvextract`、`libexec/mkvinfo`、`libexec/mkvpropedit`
- **版本** {{MKVTOOLNIX_VERSION}}
- **许可证** {{MKVTOOLNIX_LICENSE}}
- **源码** {{MKVTOOLNIX_SOURCE}}
- **许可原文** {{MKVTOOLNIX_LICENSE_FILES}}

---

## mpv

- **文件** `libexec/mpv` 及 `mpv/` 中的右键菜单
- **版本** {{MPV_VERSION}}
- **许可证** [GPL-2.0-or-later](mpv/LICENSE.GPL)，部分代码采用 [LGPL](mpv/LICENSE.LGPL)。
- **源码** {{MPV_SOURCE}}

### libplacebo 渲染库

- **文件** 链接到 `libexec/mpv` 的 libplacebo
- **版本** {{LIBPLACEBO_MPV_VERSION}}
- **许可证** [随附许可证及依赖声明](libplacebo-mpv/LICENSE)
- **源码** {{LIBPLACEBO_MPV_SOURCE}}

---

## uosc

- **文件** `mpv/scripts/uosc/`（含原生 Ziggy 辅助工具）及 `mpv/fonts/` 中的 uosc 字体
- **版本** {{UOSC_VERSION}}
- **许可证** [LGPL-2.1](uosc/LICENSE.LGPL)。Ziggy 依赖的许可声明见 `legal/uosc/`。
- **源码** {{UOSC_SOURCE}}

## mpv-lazy 着色器

随附播放预设与着色器含有各自的[源码及许可声明](mpv_lazy_shaders/COPYRIGHT.zh-Hans.md)。

---

## VapourSynth 与 Python 共享运行时

程序与 VSScript 共用 `python/` 中的 CPython 及 NumPy。

### VapourSynth

- **文件** `{{SITE_PACKAGES}}/vapoursynth/`，包含核心、Python 模块、VSScript 和 VSPipe
- **版本** {{VAPOURSYNTH_VERSION}}
- **许可证** [LGPL-2.1-or-later](vapoursynth/COPYING.LESSER)
- **源码** {{VAPOURSYNTH_SOURCE}}

### CPython

- **文件** `python/` 中的解释器与标准库
- **版本** {{PYTHON_VERSION}}
- **许可证** {{PYTHON_LICENSE}}
- **源码** {{PYTHON_SOURCE}}
- **许可原文** {{PYTHON_LICENSE_FILES}}

### NumPy

- **文件** `{{SITE_PACKAGES}}/numpy/` 及随附原生库
- **版本** {{NUMPY_VERSION}}
- **许可证** {{NUMPY_LICENSE}}
- **源码** {{NUMPY_SOURCE}}
- **许可原文** {{NUMPY_LICENSE_FILES}}

### VapourSynth Python 滤镜脚本

随附脚本保留[版权、源码及许可声明](vapoursynth_scripts/COPYRIGHT.zh-Hans.md)。许可原文位于 `legal/vapoursynth_scripts/licenses/`。

### 原生滤镜插件

`plugins/` 中的原生滤镜使用下表所列的源码和版本。

| 组件 | 版本或修订 | 源码 | 随附许可文件目录 |
| --- | --- | --- | --- |
{{VAPOURSYNTH_COMPONENTS}}

---

## VapourSynth Editor

- **文件** `libexec/vsedit`
- **版本** {{VSEDIT_VERSION}}
- **许可证** [MIT](vsedit/LICENSE)
- **源码** {{VSEDIT_SOURCE}}

---

## Qt 与 PyQt6

### Qt

- **文件** `lib/` 中的 Qt 共享库及 `qt/` 中的插件和翻译
- **版本** {{QT_VERSION}}
- **许可证** [Qt 开源许可条款](https://doc.qt.io/qt-6/licensing.html)。各模块的具体条款见相应的许可声明。
- **源码** {{QT_SOURCE}}
- **许可原文** {{QT_LICENSE_FILES}}

### PyQt6

- **文件** `{{SITE_PACKAGES}}/PyQt6/` Python 绑定
- **版本** {{PYQT_VERSION}}
- **许可证** {{PYQT_LICENSE}}
- **源码** {{PYQT_SOURCE}}
- **许可原文** {{PYQT_LICENSE_FILES}}

---

## SoundFile 与 libsndfile

### SoundFile

- **文件** SoundFile Python 模块
- **版本** {{SOUNDFILE_VERSION}}
- **许可证** {{SOUNDFILE_LICENSE}}
- **源码** {{SOUNDFILE_SOURCE}}
- **许可原文** {{SOUNDFILE_LICENSE_FILES}}

### libsndfile

- **文件** `lib/libsndfile.so.1`
- **版本** {{LIBSNDFILE_VERSION}}
- **许可证** {{LIBSNDFILE_LICENSE}}
- **源码** {{LIBSNDFILE_SOURCE}}
- **许可原文** {{LIBSNDFILE_LICENSE_FILES}}

---

## Pillow 与 pycountry

### Pillow

- **文件** `{{SITE_PACKAGES}}/PIL/`
- **版本** {{PILLOW_VERSION}}
- **许可证** {{PILLOW_LICENSE}}
- **源码** {{PILLOW_SOURCE}}
- **许可原文** {{PILLOW_LICENSE_FILES}}

### pycountry

- **文件** `{{SITE_PACKAGES}}/pycountry/` 及随附的 ISO 数据集
- **版本** {{PYCOUNTRY_VERSION}}
- **许可证** {{PYCOUNTRY_LICENSE}}
- **源码** {{PYCOUNTRY_SOURCE}}
- **许可原文** {{PYCOUNTRY_LICENSE_FILES}}

---

## 其他随附库

下表按 FreeBSD Ports 发布的许可声明列出其他随附库。Ports 提供的许可文件收集于 `legal/ports/`，随附 FreeBSD 基础系统库的许可原文位于 `legal/freebsd-base/`。

| 组件 | 版本 | 许可证 | 源码 |
| --- | --- | --- | --- |
{{ADDITIONAL_COMPONENTS}}
