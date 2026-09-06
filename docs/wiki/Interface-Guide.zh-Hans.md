# 界面展示及说明

[English](Interface-Guide.md) | 简体中文

> 截图使用示例原盘说明操作；不同版本的布局和默认值可能不同，实际以当前界面为准。

## 主窗口的内容分区

顶部语言、主题、字体和设置栏及底部执行按钮保持固定，其余内容通过页面右侧滚动条查看。三张表分别说明原盘播放列表、正片输出和 SP；表格内滚动条用于查看更多行或列。可拖动列边界调整宽度，悬停查看完整文字；原盘信息行也可拖高以显示更多 MPLS。自动生成的行仍需按实际内容检查。

《魔女的使命》的连体盘示例展示了多个正片范围、短 SP 和 `igs_menu` 项目同时存在的情况。正片行应按实际集数检查起止章节；菜单类 IGS 通常不作为普通 Matroska 字幕轨道输出。

[![《魔女的使命》连体盘界面](https://sbx.mysmy.top/pictures/%E9%AD%94%E5%A5%B3%E7%9A%84%E4%BD%BF%E5%91%BD%20%E8%BF%9E%E4%BD%93%E7%9B%98.png)](https://sbx.mysmy.top/pictures/%E9%AD%94%E5%A5%B3%E7%9A%84%E4%BD%BF%E5%91%BD%20%E8%BF%9E%E4%BD%93%E7%9B%98.png)

《狼与香辛料》的多卷示例展示了不同分卷各自拥有主 MPLS、分集和 SP 的情况。处理这类原盘时，应逐卷确认分集边界和 SP 选择，不能因为各卷表格结构相似就假定内容也完全相同。

[![《狼与香辛料》多卷界面](https://sbx.mysmy.top/pictures/%E7%8B%BC%E4%B8%8E%E9%A6%99%E8%BE%9B%E6%96%99%20%E8%82%89%E9%85%B1%E7%9B%98.png)](https://sbx.mysmy.top/pictures/%E7%8B%BC%E4%B8%8E%E9%A6%99%E8%BE%9B%E6%96%99%20%E8%82%89%E9%85%B1%E7%9B%98.png)

## 查看 MPLS 的章节、播放项和轨道

“查看章节”“查看时间”和“编辑轨道”描述的是同一 MPLS 的不同层面：章节适合决定输出段落，M2TS 时间适合核对每个 PlayItem 实际引用的源区间，轨道界面则决定最终保留哪些逻辑轨道。

### 查看章节

“查看章节”按输出时间轴列出章节区间及其所在 M2TS。对于主 MPLS，取消某个区间的勾选会把它排除在对应正片输出之外；需要保留的未选内容可以在 SP 表中另行确认。

[![《疯狂动物城 2》查看章节](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E7%AB%A0%E8%8A%82.png)](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E7%AB%A0%E8%8A%82.png)

### 查看 M2TS 时间

“查看时间”逐个列出 PlayItem 的 M2TS、`INTime`、`OUTTime`、片段时长以及它在 MPLS 时间轴上的起止点。MPLS 引用的通常只是 M2TS 的一个区间，因此不能把“使用了这个 M2TS”理解为“应复制整个文件”。

[![《疯狂动物城 2》查看 M2TS 时间](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E6%97%B6%E9%97%B4.png)](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E6%9F%A5%E7%9C%8B%E6%97%B6%E9%97%B4.png)

### 编辑轨道

在**编辑轨道**中勾选所需行，悬停状态查看逐 PlayItem 明细；逻辑轨道身份及格式限制见 [STN 模型](Blu-ray-Disc-Structure.zh-Hans.md#stn-表)。

《疯狂动物城 2》的示例中，音频和字幕状态会直接显示 `eng → zho → eng`，提示信息进一步列出各 PlayItem 的语言和 PID。语言变化是提示，不会把一条逻辑轨道拆成多条。

[![《疯狂动物城 2》编辑轨道](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)](https://sbx.mysmy.top/pictures/%E7%96%AF%E7%8B%82%E5%8A%A8%E7%89%A9%E5%9F%8E2%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)

《阿凡达》中标为**部分片段缺失**的轨道未覆盖全部 PlayItem；实际 M2TS 中的缺轨遵循[部分缺失选项](../../README.zh-Hans.md#remux-控制)。

[![《阿凡达》部分片段缺失轨道](https://sbx.mysmy.top/pictures/%E9%98%BF%E5%87%A1%E8%BE%BE%2000150.mpls%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)](https://sbx.mysmy.top/pictures/%E9%98%BF%E5%87%A1%E8%BE%BE%2000150.mpls%20%E7%BC%96%E8%BE%91%E8%BD%A8%E9%81%93.png)

## 示例：避免重复片段让 Remux 体积膨胀

《花样少年少女》的正片共 12 集，BD 还额外收录三集 Non Credit（NC）版本，前三卷各有一集。部分 MPLS 之间存在内容重叠；如果把它们全部作为独立内容 Remux，同一物理片段会进入多个输出，最终总大小可能超过原盘中唯一数据的体积。这是 README FAQ 中“为什么 remux 出来的体积比原盘大”的一种典型情况。

[![《花样少年少女》剧集 Remux 界面](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3.png)](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3.png)

以第二卷为例，`00000.mpls` 和 `00001.mpls` 都覆盖三集内容，其中 `00001.m2ts` 和 `00003.m2ts` 是重复引用，`00005.m2ts` 则是 `00004.m2ts` 对应剧集的 NC 版本。可以把 `00000.mpls` 用作普通正片来源，并保留它的正常章节区间：

[![《花样少年少女》第二卷 00000.mpls](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000000.mpls.png)](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000000.mpls.png)

在 `00001.mpls` 中取消前 12 个重复章节区间，只保留从 Chapter 13 开始的 NC 内容。主界面截图中的 Table 3 第 8 行也不需要输出，应再取消该行勾选。这样既保留普通三集和额外 NC 版本，又不会把重复正片再次写入输出。

[![《花样少年少女》第二卷 00001.mpls 章节选择](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000001.mpls.png)](https://sbx.mysmy.top/pictures/%E8%8A%B1%E6%A0%B7%E5%B0%91%E5%B9%B4%E5%B0%91%E5%A5%B3%20%E7%AC%AC%E4%BA%8C%E5%8D%B7%2000001.mpls.png)

## 示例：为什么必须遵守 INTime 和 OUTTime

《转生七王子》第二季第一卷的 `00004.mpls` 是第一集的 NC 版本，主体内容取自第一集对应的 `00002.m2ts`，`00009.m2ts` 和 `00010.m2ts` 则是 NC 片段。章节界面显示的是组合完成后的 MPLS 时间轴：

[![《转生七王子》第二季第一卷 00004.mpls 章节](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20%E7%AB%A0%E8%8A%82.png)](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20%E7%AB%A0%E8%8A%82.png)

M2TS 时间界面可以看到 `00002.m2ts` 被分成不同区间，并与 `00009.m2ts`、`00010.m2ts` 依次组合。如果忽略 `INTime` 和 `OUTTime` 而整段复制 M2TS，就会带入播放列表没有引用的内容，也无法还原制作方编排的 NC 版本。

[![《转生七王子》第二季第一卷 00004.mpls 播放项](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20m2ts%20%E6%97%B6%E9%97%B4.png)](https://sbx.mysmy.top/pictures/%E8%BD%AC%E7%94%9F%E4%B8%83%E7%8E%8B%E5%AD%90%20%E7%AC%AC%E4%BA%8C%E5%AD%A3%20%E7%AC%AC%E4%B8%80%E5%8D%B7%2000004.mpls%20m2ts%20%E6%97%B6%E9%97%B4.png)

## 示例：完整匹配 MPLS 提供额外轨道

《Re:Zero》第三季第一卷中，`00001.mpls` 和完整时间线匹配的 `00002.mpls` 分别暴露一条 PCM 音轨。程序把它们显示在同一个“编辑轨道”界面中，并标明各自的来源 MPLS；只要物理 M2TS/PID 对应关系不重复，两条音轨都可以加入同一个主输出。IGS 行保持可见但置灰，因为 Matroska 不支持把交互图形作为普通字幕轨道混流。

[![《Re:Zero》第三季第一卷完整 MPLS 轨道附加](https://sbx.mysmy.top/pictures/Re%20Zero%20%E7%AC%AC%E4%B8%89%E9%9B%86%20%E7%AC%AC%E4%B8%80%E5%8D%B7%20%E6%95%B4%E6%9D%A1%20mpls%20%E9%99%84%E5%8A%A0.png)](https://sbx.mysmy.top/pictures/Re%20Zero%20%E7%AC%AC%E4%B8%89%E9%9B%86%20%E7%AC%AC%E4%B8%80%E5%8D%B7%20%E6%95%B4%E6%9D%A1%20mpls%20%E9%99%84%E5%8A%A0.png)

这个行为的完整规则见[蓝光原盘结构：SP 轨道和被 MPLS 隐藏的轨道](Blu-ray-Disc-Structure.zh-Hans.md#sp-轨道和被-mpls-隐藏的轨道)。

## 操作建议

1. 先根据时长和播放结果确定主 MPLS，不要只看编号。
2. 用“查看章节”决定正片或分集的输出范围。
3. 用“查看时间”核对重复片段、片段顺序和 `INTime`／`OUTTime`。
4. 在“编辑轨道”中确认最终视频、音频和字幕选择，并阅读异常状态的提示。
5. 最后检查 SP 表，取消重复、无用或不希望单独输出的项目。
