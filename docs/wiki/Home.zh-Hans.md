# BluraySubtitle 项目文档

[English](Home.md) | 简体中文

安装和基本操作从 [README](../../README.zh-Hans.md) 开始，详细说明按主题查阅下表。

| 主题 | 主要文档 |
| --- | --- |
| 表格、轨道对话框及真实原盘选择示例 | [界面展示及说明](Interface-Guide.zh-Hans.md) |
| 容器、轨道、抽流／重混流、编码与无损音频 | [媒体基础概念](Media-Fundamentals.zh-Hans.md) |
| BDMV 结构、播放列表时间、主 MPLS 与 SP 规则 | [蓝光原盘结构](Blu-ray-Disc-Structure.zh-Hans.md) |
| 视频／音频编码、字幕格式及 Dolby Vision 分层 | [媒体格式、字幕与 Dolby Vision](Media-Formats-and-Dolby-Vision.zh-Hans.md) |
| 编码器设置、VPy 滤镜、预览、getnative 与 HDR 处理 | [视频压制与 VapourSynth](Video-Encoding-and-VapourSynth.zh-Hans.md) |
| 源码导航、标识符及分集配置 | [开发者指南](BluraySubtitle-Developer-Guide.zh-Hans.md) |
| Remux 回退、音频处理及外部工具选型依据 | [媒体处理流程与工具选型](../development/media-pipeline-and-tool-selection.zh-Hans.md) |
| 修改要求 | [代码修改规范](../development/code-standards.zh-Hans.md) |
| 格式规范及上游手册 | [参考资料](References.zh-Hans.md) |

新用户可先看界面示例，再按需查阅概念。开发者应先读代码规范，再看开发者指南及相关处理流程。

Wiki 覆盖媒体识别、提取、重混流和压制，不实现完整的 HDMV／BD-J 导航、原盘解密或原盘制作。二进制结构说明以项目解析器和参考资料中列出的来源为依据。
