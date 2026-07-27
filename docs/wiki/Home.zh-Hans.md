# BluraySubtitle 项目文档

[English](Home.md) | 简体中文

本文档解释 BluraySubtitle 涉及的媒体概念，并将这些概念与项目实现对应起来。主要面向两类读者：

- 希望可靠理解蓝光原盘、Matroska、轨道、重混流、压制、字幕、音频、视频和 Dolby Vision 的用户；
- 需要了解二进制结构、时间规则、源码位置和工作流约束的开发者。

如果你还不熟悉“容器”“轨道”“抽流”“无损”等术语，请先阅读[媒体基础概念](Media-Fundamentals.zh-Hans.md)。随后可通过[蓝光原盘结构](Blu-ray-Disc-Structure.zh-Hans.md)了解 BDMV、MPLS、CLPI、M2TS、播放列表时间和章节。编解码器、音频与字幕的细节集中在[媒体格式、字幕与 Dolby Vision](Media-Formats-and-Dolby-Vision.zh-Hans.md)；[视频压制与 VapourSynth](Video-Encoding-and-VapourSynth.zh-Hans.md)则介绍编码选择、参数预设、帧处理和项目压制管线。

开发者还应阅读 [BluraySubtitle 开发者指南](BluraySubtitle-Developer-Guide.zh-Hans.md)。该文档定义项目中 **主 MPLS** 和 **SP** 的含义，介绍扫描与重混流管线，并指向相关源码。

## 项目术语速览

以下定义属于本项目，不应与蓝光规范中的术语混淆：

- **主 MPLS**：所选原盘播放列表，其编排的播放内容属于正片、电影主体或剧集主体。主 MPLS 不一定是编号最小、体积最大或时长最长的播放列表。
- **SP**：所选主播放列表内容之外的所有附加原盘内容，包括其他播放列表、主 MPLS 中未勾选的片段，以及没有被播放列表覆盖但有用的 M2TS。这里的 `SP` 是 BluraySubtitle 的内容分类，不是蓝光文件格式或规范术语。
- **原盘／蓝光源**：在项目的一般语境中，指能够读取并呈现 BDMV 结构的蓝光目录或已挂载镜像。应用本身不负责解密无法读取的扇区。
- **Remux／重混流**：不重新编码视频，将所选编码流写入新容器。BluraySubtitle 的 Remux 任务仍可能执行用户明确选择或项目明确记录的音频转换与清理，因此最终文件不一定逐字节保留每条源流。
- **Encode／压制**：解码并重新编码视频，可在编码前执行预处理，最后将结果与所选音频、字幕、章节和元数据混流。

## 推荐阅读顺序

### 仅使用应用

1. [媒体基础概念](Media-Fundamentals.zh-Hans.md)
2. [蓝光原盘结构](Blu-ray-Disc-Structure.zh-Hans.md)，至少读到“MPLS、M2TS 与 CLPI 如何协作”
3. [媒体格式、字幕与 Dolby Vision](Media-Formats-and-Dolby-Vision.zh-Hans.md)
4. [视频压制与 VapourSynth](Video-Encoding-and-VapourSynth.zh-Hans.md)，适合使用压制功能的用户
5. 项目[简体中文 README](../../README.zh-Hans.md)

### 理解或修改项目实现

1. 上述全部用户文档
2. [BluraySubtitle 开发者指南](BluraySubtitle-Developer-Guide.zh-Hans.md)
3. [媒体管线设计与工具选择](../development/media-pipeline-and-tool-selection.zh-Hans.md)
4. [代码修改规范](../development/code-standards.zh-Hans.md)

## 内容范围

本文档重点介绍影响蓝光内容识别、提取、重混流、压制和保留的部分。导航文件只解释到足以定位编排播放路径的程度；本文并非 HDMV 虚拟机、BD-J、AACS、BD+、区域控制或蓝光制作的完整实现指南。

二进制细节以项目解析器、公开的 [lw/BluRay Wiki](https://github.com/lw/BluRay/wiki)，以及[参考资料](References.zh-Hans.md)列出的规范和开源实现为依据。
