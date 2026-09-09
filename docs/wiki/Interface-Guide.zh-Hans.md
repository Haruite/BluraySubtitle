# 界面展示及说明

[English](Interface-Guide.md) | 简体中文

> 截图使用示例原盘说明操作；不同版本的布局和默认值可能不同，实际以当前界面为准。

## 主窗口的内容分区

顶部语言、主题、字体和设置栏及底部执行按钮保持固定，其余内容通过页面右侧滚动条查看。三张表分别说明原盘播放列表、正片输出和 SP；表格内滚动条用于查看更多行或列。可拖动每张表底部的调节条调整高度，拖动列边界调整宽度，悬停查看完整文字；原盘信息行也可拖高以显示更多 MPLS。自动生成的行仍需按实际内容检查。

《魔女的使命》示例只勾选前两碟，得到 12 集 TV，特典碟另行处理。应按实际内容检查估算的分集边界：这里 EP05、EP11 的结束章节设为 31，相邻下一集的起始章节也随之变为 31。SP 表同时列出短片和 `igs_menu`；交互菜单图形不能作为普通 Matroska 字幕轨道混流。

[![《魔女的使命》连体盘界面](https://sbx.mysmy.top/pictures/interface-20260910-joined-disc-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-joined-disc-zh.jpg)

## 原盘选择与顺序

通过原盘路径旁的勾选框选择要处理的卷。将路径行拖到另一行之前或之后调整顺序，点击列标题可按该列排序。未勾选的原盘仍保留在列表中，但其正片和 SP 不参与输出。

更改原盘选择或顺序后，下方输出表会重新生成。执行前请检查分集编号、输出名称、章节范围和外挂字幕。原盘序号对应当前来源表中的行号，包含未勾选行；分集编号则按已选择的内容排列。

《狼与香辛料》的文件夹按名称排列为第 2 卷、第 4 卷、DISC 1、第 3 卷；截图展示手动调整前 DISC 1 位于来源表第 3 行的情况。拖动路径排成剧情顺序后，检查重新生成的分集编号和文件名，并逐卷确认章节边界及 SP 选择。

[![《狼与香辛料》多卷界面](https://sbx.mysmy.top/pictures/interface-20260910-disc-order-input-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-disc-order-input-zh.jpg)

### 字幕合并中的目录与 ISO 混合输入

《钢之炼金术师 FULLMETAL ALCHEMIST》的输入同时包含 ISO 和已解压的原盘目录。在“生成合并字幕”中，ISO 只提供播放列表，无需解压媒体；ISO 不支持预览、Remux 或 Encode。按完整路径排序后，先核对卷号，再匹配字幕。图中第 11 卷为 ISO，第 12 卷为目录。

[![钢炼 ISO 与目录混合输入](https://sbx.mysmy.top/pictures/interface-20260910-mixed-iso-subtitles-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-mixed-iso-subtitles-zh.jpg)

## 示例：同盘包含两个电影版本

《黑鹰坠落》在电影模式下选中 `00501.mpls` 和 `00503.mpls`，时长分别为 02:24:18.649、02:31:50.601，输出表使用不同的 `_1`、`_2` 文件名。与它们完整重复的 `00502.mpls`、`00504.mpls` 不勾选。

[![黑鹰坠落的两个主电影版本](https://sbx.mysmy.top/pictures/interface-20260910-movie-two-versions-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-two-versions-zh.jpg)

多条长播放列表不一定代表多个版本。例如《疯狂动物城 2》只保留主列表 `00800.mpls`；增加主列表前，应核对内容和轨道差异。

## 查看 MPLS 的章节、播放项和轨道

“查看章节”“查看时间”和“编辑轨道”描述的是同一 MPLS 的不同层面：章节适合决定输出段落，M2TS 时间适合核对每个 PlayItem 实际引用的源区间，轨道界面则决定最终保留哪些逻辑轨道。

### 查看章节

“查看章节”按输出时间轴列出章节区间及其所在 M2TS。在 Remux／Encode 中，取消已选主 MPLS 的某个区间，会把它排除在对应正片输出之外，生成的 SP 行应另行检查。非主播放列表的章节窗口只读；需要修改章节选择时，先将该列表勾选为主 MPLS。

[![《疯狂动物城 2》查看章节](https://sbx.mysmy.top/pictures/interface-20260910-movie-chapters-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-chapters-zh.jpg)

#### 排除与正片交替排列的广播剧

《ODDTAXI》两卷的 `00000.mpls` 都交替串联正片与广播剧。保留这两条主列表，在“查看章节”中取消广播剧区间的勾选：

- 第一卷：Chapter 6、12、18、24、30、35、41。
- 第二卷：Chapter 5、11、17、22、28、31。

这样得到 7＋6 集 TV 范围；被排除的广播剧成为独立的章节片段 SP，可在 SP 表中决定是否保留。下图展示第一卷章节选择的前半部分。

[![ODDTAXI 取消广播剧章节勾选](https://sbx.mysmy.top/pictures/interface-20260910-audio-drama-chapters-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-audio-drama-chapters-zh.jpg)

### 查看 M2TS 时间

“查看时间”逐个列出 PlayItem 的 M2TS、`INTime`、`OUTTime`、片段时长以及它在 MPLS 时间轴上的起止点。IN／OUT 列使用 45 kHz 时间刻度，时长及时间轴位置使用时码。MPLS 引用的通常只是 M2TS 的一个区间，因此不能把“使用了这个 M2TS”理解为“应复制整个文件”。

[![《疯狂动物城 2》查看 M2TS 时间](https://sbx.mysmy.top/pictures/interface-20260910-movie-playitems-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-playitems-zh.jpg)

### 编辑轨道

在**编辑轨道**中勾选所需行，悬停状态查看逐 PlayItem 明细；逻辑轨道身份及格式限制见 [STN 模型](Blu-ray-Disc-Structure.zh-Hans.md#stn-表)。

《疯狂动物城 2》的示例中，音频和字幕状态会直接显示 `eng → zho → eng`，提示信息进一步列出各 PlayItem 的语言和 PID。语言变化是提示，不会把一条逻辑轨道拆成多条。

[![《疯狂动物城 2》编辑轨道](https://sbx.mysmy.top/pictures/interface-20260910-movie-tracks-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-movie-tracks-zh.jpg)

《阿凡达：水之道》`00150.mpls` 中标为**部分片段缺失**的音轨未覆盖全部 PlayItem；实际 M2TS 中的缺轨遵循[部分缺失选项](../../README.zh-Hans.md#remux-控制)。

[![《阿凡达：水之道》部分片段缺失轨道](https://sbx.mysmy.top/pictures/interface-20260910-missing-track-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-missing-track-zh.jpg)

## 示例：避免重复片段让 Remux 体积膨胀

《花样少年少女》的正片共 12 集，BD 还额外收录三集 Non Credit（NC）版本，前三卷各有一集。部分 MPLS 之间存在内容重叠；如果把它们全部作为独立内容 Remux，同一物理片段会进入多个输出，最终总大小可能超过原盘中唯一数据的体积。这是 README FAQ 中“为什么 remux 出来的体积比原盘大”的一种典型情况。

以第二卷为例，`00000.mpls` 和 `00001.mpls` 都覆盖三集内容，其中 `00001.m2ts` 和 `00003.m2ts` 是重复引用，`00005.m2ts` 则是 `00004.m2ts` 对应剧集的 NC 版本。将两条播放列表都勾选为主 MPLS；`00000.mpls` 保留全部正常章节区间：

[![《花样少年少女》第二卷 00000.mpls](https://sbx.mysmy.top/pictures/interface-20260910-hana-regular-chapters-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-hana-regular-chapters-zh.jpg)

在 `00001.mpls` 中取消前 12 个重复章节区间，只保留从 Chapter 13 开始的 NC 内容。这样既保留普通三集和额外 NC 版本，又不会把重复剧集再次写入输出。

[![《花样少年少女》第二卷 00001.mpls 章节选择](https://sbx.mysmy.top/pictures/interface-20260910-hana-nc-chapters-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-hana-nc-chapters-zh.jpg)

第二卷的输出行现在包含三个普通版和一个 NC 版。额外的主输出也会占用分集编号，执行前应核对它的文件名及后续编号，并检查 SP 表中是否还有不希望导出的重叠内容。

[![《花样少年少女》剧集 Remux 界面](https://sbx.mysmy.top/pictures/interface-20260910-hana-outputs-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-hana-outputs-zh.jpg)

## 示例：为什么必须遵守 INTime 和 OUTTime

《转生七王子》第二季第一卷的 `00004.mpls` 是第一集的 NC 版本，主体内容取自第一集对应的 `00002.m2ts`，`00009.m2ts` 和 `00010.m2ts` 则是 NC 片段。章节界面显示的是组合完成后的 MPLS 时间轴：

[![《转生七王子》第二季第一卷 00004.mpls 章节](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-chapters-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-chapters-zh.jpg)

M2TS 时间界面可以看到 `00002.m2ts` 被分成不同区间，并与 `00009.m2ts`、`00010.m2ts` 依次组合。如果忽略 `INTime` 和 `OUTTime` 而整段复制 M2TS，就会带入播放列表没有引用的内容，也无法还原制作方编排的 NC 版本。

[![《转生七王子》第二季第一卷 00004.mpls 播放项](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-playitems-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-nc-splice-playitems-zh.jpg)

## 示例：完整匹配 MPLS 提供额外轨道

《Re:Zero》第三季第一卷中，`00001.mpls` 和完整时间线匹配的 `00002.mpls` 分别暴露一条 PCM 音轨。程序把它们显示在同一个“编辑轨道”界面中，并标明各自的来源 MPLS；只要物理 M2TS/PID 对应关系不重复，两条音轨都可以加入同一个主输出。IGS 行保持可见但置灰，因为 Matroska 不支持把交互图形作为普通字幕轨道混流。

[![《Re:Zero》第三季第一卷完整 MPLS 轨道附加](https://sbx.mysmy.top/pictures/interface-20260910-whole-playlist-tracks-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-whole-playlist-tracks-zh.jpg)

这个行为的完整规则见[蓝光原盘结构：SP 轨道和被 MPLS 隐藏的轨道](Blu-ray-Disc-Structure.zh-Hans.md#sp-轨道和被-mpls-隐藏的轨道)。

## 示例：同一集附加两个评论轨提供者

《葬送的芙莉莲》第二季第三卷中，`00004.mpls`、`00005.mpls` 都匹配该卷第一集，并分别提供 PID 4353、4354 的评论音轨。三卷全部勾选时，两条 SP 行都指向 EP08 输出，各自选中的轨道都会追加到这一集；可分别打开“编辑轨道”检查。

[![芙莉莲两个评论播放列表附加到 EP08](https://sbx.mysmy.top/pictures/interface-20260910-episode-commentary-providers-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-episode-commentary-providers-zh.jpg)

时长列显示来源播放列表的时长。循环菜单因此可能显示远长于实际保留片段的时间；执行时会按菜单处理规则缩短，检查这类行时可查看其 PlayItem 结构。

## 示例：特典盘不设置正片

《Sonny Boy》的 BONUS 盘在来源表中保持勾选，只取消其 `00035.mpls` 的“主播放列表”按钮。前两碟提供 12 集 TV，特典盘的内容进入 SP 表。

[![Sonny Boy 特典盘保持勾选但不选择主列表](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-no-main-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-no-main-zh.jpg)

完整的 48:52.805 花絮以现有章节范围输出为 `BD_Vol_003_SP06.mkv`。表中还可看到静态内容对应的 PNG 和图片目录；按 [SP 输出规则](Blu-ray-Disc-Structure.zh-Hans.md#sp-选择与输出)检查选择与名称。

[![Sonny Boy 完整花絮及静态图片 SP 输出](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-sp-zh.jpg)](https://sbx.mysmy.top/pictures/interface-20260910-bonus-disc-sp-zh.jpg)

## 操作建议

1. 先根据时长和播放结果确定主 MPLS，不要只看编号。
2. 用“查看章节”决定正片或分集的输出范围。
3. 用“查看时间”核对重复片段、片段顺序和 `INTime`／`OUTTime`。
4. 在“编辑轨道”中确认最终视频、音频和字幕选择，并阅读异常状态的提示。
5. 最后检查 SP 表，取消重复、无用或不希望单独输出的项目。
