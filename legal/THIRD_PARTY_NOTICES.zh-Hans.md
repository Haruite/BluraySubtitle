# 第三方许可声明（随附二进制文件）

**产品：** BluraySubtitle（Windows，PyInstaller 单目录构建）

运行 `BluraySubtitle_windows_x64.spec` 时，会根据所选的随附组件更新版本字段。

---

## 7-Zip

- **文件：** `7z.exe`、`7z.dll`
- **版本：** {{SEVEN_ZIP_VERSION}}
- **许可：** GNU LGPL，部分代码采用 BSD-3-Clause，并包含 unRAR 限制
- **许可原文：** 随附于 `legal/7zip/License.txt`；上游：https://www.7-zip.org/license.txt
- **源码：** https://github.com/ip7z/7zip/tree/{{SEVEN_ZIP_VERSION}}

---

## FFmpeg / FFprobe

- **文件：** `ffmpeg.exe`、`ffprobe.exe`
- **随附构建：** `ffmpeg-{{FFMPEG_BUILD}}`
- **许可证：** GPL v3
- **此构建的源码：** https://github.com/FFmpeg/FFmpeg/tree/n{{FFMPEG_VERSION}}

**商标：** 重新分发 FFmpeg 二进制文件时，请遵守 FFmpeg 的商标政策：https://ffmpeg.org/legal.html

---

## FLAC / libFLAC

- **文件：** `flac.exe`、`libFLAC.dll`
- **版本：** {{FLAC_VERSION}}
- **许可证：** BSD-3-Clause
- **源码：** https://ftp.osuosl.org/pub/xiph/releases/flac/flac-{{FLAC_VERSION}}.tar.xz

---

## fdkaac（命令行编码器）+ FDK-AAC（库）

它们来自**两个独立的上游项目**：`fdkaac` 程序链接或随附 **FDK-AAC** 库的构建产物。

### fdkaac — https://github.com/nu774/fdkaac

- **随附文件：** `fdkaac.exe`
- **版本：** **v{{FDKAAC_VERSION}}**
- **许可证：**
  - 项目大部分代码采用 **Zlib License**，SPDX 标识为 **`Zlib`**。
  - 随附源码还包含 **MIT**（如 `parson`）、**BSD-4-clause**（如 `getopt`）和 **BSD 风格许可证**（如 `lpc.c` / `lpc.h`），均列在同一个 `COPYING` 文件中。
- **许可证全文（此标签）：** https://raw.githubusercontent.com/nu774/fdkaac/v{{FDKAAC_VERSION}}/COPYING
- **源码（标签对应目录树）：** https://github.com/nu774/fdkaac/tree/v{{FDKAAC_VERSION}}
- **源码归档（可重复获取的 tar 包）：** https://github.com/nu774/fdkaac/archive/refs/tags/v{{FDKAAC_VERSION}}.tar.gz

### Fraunhofer FDK AAC Codec Library — https://github.com/mstorsjo/fdk-aac

- **随附方式：** 静态链接到 `fdkaac.exe`
- **版本：** **v{{FDK_AAC_VERSION}}**
- **许可证：** Fraunhofer 的 **“Software License for The Fraunhofer FDK AAC Codec Library for Android”**，属于**项目专用许可证**（上游以 **`NOTICE`** 文件提供）。它不是 Apache-2.0 或 LGPL，也**没有一个被广泛采用的统一 SPDX 标识**；部分清单根据内部政策使用自定义 `LicenseRef-…`。
- **许可证全文（此标签）：** https://raw.githubusercontent.com/mstorsjo/fdk-aac/v{{FDK_AAC_VERSION}}/NOTICE
- **源码（标签对应目录树）：** https://github.com/mstorsjo/fdk-aac/tree/v{{FDK_AAC_VERSION}}
- **源码归档（可重复获取的 tar 包）：** https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v{{FDK_AAC_VERSION}}.tar.gz

**重新分发说明：** 分发二进制文件时，尤其需要在文档或随附材料中**保留完整许可证文本**，并向二进制文件接收者**免费提供 FDK AAC Codec 的完整源码及你的修改（如有）**。**该许可证不授予专利权**；部分 AAC 用途可能需要另行取得专利许可（上游指向 Via Licensing／专利权人）。

**专利与产品合规：** 本节**不构成法律意见**。向最终用户分发 AAC 编码器时，应针对产品和所在地区单独确认**专利与许可**要求，不能只依据上述版权许可证文本判断。

---

## x264

- **文件：** `x264.exe`、`/usr/bin/x264`
- **版本：** `{{X264_VERSION}}`
- **许可证：** GPL-2.0
- **官方仓库：** https://code.videolan.org/videolan/x264.git
- **构建说明：** 使用未经修改的官方源码，构建为支持 8/10 位的命令行程序；Windows setup 还使用 PGO。

---

## x265

- **文件：** `x265.exe`、`/usr/bin/x265`
- **版本：** {{X265_VERSION}}
- **许可证：** GPL-2.0
- **此构建的源码：** https://github.com/Multicorewareinc/x265/tree/{{X265_VERSION}}
- **构建说明：** 使用官方源码，构建为静态链接的 8/10/12 位 multilib 命令行程序，并在目标平台上启用原生 HDR10+ JSON 输入支持，包括 Docker 使用的 Ubuntu 26.04。受管理的构建会向上游 `dynamicHDR10/json11/json11.cpp` 添加缺失的 `<cstdint>` 头文件，以兼容当前 C++ 编译器。

---

## SVT-AV1（SvtAv1EncApp）

- **文件：** `SvtAv1EncApp.exe`
- **版本：** v{{SVT_AV1_VERSION}}
- **许可证：** BSD 3-Clause
- **源码：** https://gitlab.com/AOMediaCodec/SVT-AV1/-/archive/v{{SVT_AV1_VERSION}}/SVT-AV1-v{{SVT_AV1_VERSION}}.zip
- **构建说明：** 随附的 Windows 编码器由此标签源码构建，并使用 `setup_linux_environment.sh` 和 `Dockerfile` 中记录的 12 位应用补丁；已进行 8/10/12 位编码测试。

---

## tsMuxeR

- **文件：** `tsMuxeR.exe`
- **版本：** v{{TSMUXER_VERSION}}
- **许可证：** Apache-2.0
- **源码：** https://github.com/justdan96/tsMuxer/archive/refs/tags/{{TSMUXER_VERSION}}.zip

---

## dovi_tool

- **文件：** `dovi_tool.exe`
- **版本：** {{DOVI_TOOL_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/quietvoid/dovi_tool/archive/refs/tags/{{DOVI_TOOL_VERSION}}.zip

---

## hdr10plus_tool

- **文件：** `hdr10plus_tool.exe`、`/usr/bin/hdr10plus_tool`
- **版本：** {{HDR10PLUS_TOOL_VERSION}}
- **许可证：** MIT
- **此构建的源码：** https://github.com/quietvoid/hdr10plus_tool/tree/{{HDR10PLUS_TOOL_VERSION}}
- **构建说明：** Windows setup 下载官方 MSVC 发布版；Linux setup 和 Docker 下载官方 musl 发布版，该版本由上游启用内部字体功能构建。本项目不在本地编译此工具。

---

## libass

- **文件：** `libass-9.dll`
- **版本：** {{LIBASS_VERSION}}
- **许可证：** ISC
- **源码：** https://github.com/libass/libass/archive/refs/tags/{{LIBASS_VERSION}}.zip
- **构建方式：** MSYS2 UCRT64 共享 libass，非系统依赖采用静态链接。禁用 Fontconfig，改用 Windows DirectWrite/GDI 字体提供程序；启用 libunibreak 和 x86 汇编。随附 DLL 仅导入 Windows 系统 DLL。
- **静态链接组件：** FreeType（FTL/GPL）、FriBidi（LGPL-2.1-or-later）、HarfBuzz（MIT）、libunibreak（Zlib）、GNU libiconv/gettext（LGPL）、GLib（LGPL-2.1-or-later）、PCRE2（BSD）、Graphite2（MPL/LGPL/GPL）、Brotli（MIT）、bzip2、libpng、zlib，以及 GCC/MinGW 运行库（GPL，附带 GCC Runtime Library Exception）。源码及许可证元数据可从 https://packages.msys2.org/ 获取。

---

## MKVToolNix

- **文件：** `mkvmerge.exe`、`mkvextract.exe`、`mkvinfo.exe`、`mkvpropedit.exe`
- **版本：** v{{MKVTOOLNIX_VERSION}}
- **许可证：** GPL v2
- **许可证全文：** https://codeberg.org/mbunkus/mkvtoolnix/raw/branch/main/COPYING
- **源码：** https://codeberg.org/mbunkus/mkvtoolnix/archive/release-{{MKVTOOLNIX_VERSION}}.zip
- **说明：** 其他随附库及资源列在上游 `README.md` 的“Included third-party components and their licenses”一节中，相关许可证位于 `doc/licenses/`。

---

## VapourSynth 便携包（`vs_pkg/`）

PyInstaller 包内的 `vs_pkg/` 目录采用 **Windows x64 便携布局**，由以下**已记录的上游组件**以及你在本地添加的其他插件 DLL 组成。

### VapourSynth-Classic（核心运行时、`vspipe` 等）

- **上游：** https://github.com/AmusementClub/vapoursynth-classic
- **发布版本／标签：** {{VAPOURSYNTH_CLASSIC_VERSION}}
- **许可证：** **GNU Lesser General Public License v3**，SPDX 标识为 **`LGPL-3.0-or-later`**。
- **许可证全文（此标签）：** https://raw.githubusercontent.com/AmusementClub/vapoursynth-classic/{{VAPOURSYNTH_CLASSIC_VERSION}}/COPYING.LESSER
- **源码归档：** https://github.com/AmusementClub/vapoursynth-classic/archive/refs/tags/{{VAPOURSYNTH_CLASSIC_VERSION}}.zip

### CPython — Windows 可嵌入发行版

- **典型文件：** `vs_pkg/` 下 **embed** 布局中的 `python313.dll`、可嵌入标准库 zip 及相关文件。
- **版本：** {{PYTHON_VERSION}}（amd64 可嵌入 zip）
- **下载来源：** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/python-{{PYTHON_VERSION}}-embed-amd64.zip
- **许可证：** **Python Software Foundation License**，SPDX 标识为 **`PSF-2.0`**。
- **许可证概览：** https://docs.python.org/3/license.html
- **对应源码（CPython）：** https://www.python.org/ftp/python/{{PYTHON_VERSION}}/Python-{{PYTHON_VERSION}}.tgz

### VapourSynthScripts 与随附滤镜（AmusementClub/tools）

- **上游包：** 来自 **https://github.com/AmusementClub/tools/releases** 的发布资源。
- **版本：** {{VAPOURSYNTH_TOOLS_VERSION}}
- **许可证：** **tools** 仓库在 GitHub 上**没有统一的根目录 `LICENSE` 文件**，各组件可能采用不同许可证。

---

### VapourSynth Editor

- **文件：** `vsedit.exe`
- **版本：** {{VSEDIT_VERSION}}
- **许可证：** MIT
- **源码：** https://github.com/YomikoR/VapourSynth-Editor/archive/refs/tags/{{VSEDIT_VERSION}}.zip

---

## PyInstaller 运行时

- **文件：** 单目录包中的引导加载程序与冻结的 Python 运行时。
- **版本：** {{PYINSTALLER_VERSION}}
- **许可证：** PyInstaller 采用 **GPL-2.0-or-later**，并为引导加载程序对应用的影响提供运行时例外。请阅读当前 PyInstaller 的 `COPYING.txt`：https://github.com/pyinstaller/pyinstaller
- **源码：** https://github.com/pyinstaller/pyinstaller/releases/tag/v{{PYINSTALLER_VERSION}}

---
