# 2026-09-09～10 跨平台回归测试记录

本记录是完整测试记录的脱敏副本，面向开发者保留测试范围、复现经过、修复提交、验证结果与已知限制。日期覆盖 2026-09-09 至 2026-09-10；执行过程中的“待验证”表示当时状态，最终结果以“当前状态”和“问题与暂缓项”为准。

程序功能从浏览器中的 Linux、Docker 或 Windows GUI 执行；命令行用于环境准备、源码修改、外部工具检查与独立媒体校验。本文的 `reports/`、`screenshots/`、`state/`、`Fixtures/`、`Remux/`、`Encode/` 是外部测试归档内的相对位置，不是仓库中的附件链接。

## 浏览器控制方式

本轮通过 Codex 的 Unified Computer Use（`unified-computer-use`）插件，使用 `mcp__cua_repl.js` 的持久 JavaScript 会话和 `cua` API，经浏览器扩展控制系统 Microsoft Edge。工具负责打开或选择标签页、读取截图和网页可访问性信息，以及发送鼠标和键盘操作。

| 测试环境 | 界面控制链路 |
| --- | --- |
| Linux 宿主机 | Edge → noVNC 网页 → websockify / x11vnc → Xvfb 虚拟桌面 → 应用窗口 |
| Docker | Edge → noVNC 网页 → 宿主机 Xvfb 虚拟桌面 → 通过 X11 socket 显示的容器应用窗口 |
| Windows 虚拟机 | Edge → Guacamole 网页 → RDP → Windows 交互桌面与应用窗口 |

noVNC 和 RDP 的远程桌面显示在网页画布内，测试根据截图定位应用控件并执行点击、输入与拖动；部分拖动使用该工具暴露的 Chrome DevTools Protocol（CDP）`Input` 鼠标事件。操作后重新截图核对可见值和结果，程序流程由 GUI 启动。

## 当前状态

- 更新后的测试范围已完成，覆盖30个一级原盘输入。前29项完成 GUI、分集、SP 和命名检查；Fullmetal 按指定范围完成64集字幕合并。
- 测试基准为 `1c7eee0`，结束时源码为 `9afd36d`，期间23个提交已经合入主分支。最新运行代码及 Windows/Docker 构建为 `42cf069`；`9afd36d` 是界面文档更新。测试期间程序显示版本为4.5。
- 音频与 getnative 使用完整所选来源；视频采用完整短素材或开头360帧。按代表组合覆盖功能，没有对每个原盘重复完整压制。
- 已完成 x264 8/10、x265 8/10/12、SVT-AV1 8/10、适用音频目标、DV/RPU裁剪、HDR10+、软硬字幕、VFR与非零起点、五项图像滤镜和用户预设实际验证。
- 已完成完整评论轨附加、三种菜单循环、紫罗兰大于4GiB Wave64、字幕合并/编辑/字体、77集393章及相关输出保护。临时移动的77个章节测试原文件均已恢复。
- 最新 GUI 回归通过：混合 ISO/目录排序、64集部分勾选重新匹配、字幕合并/添加章节隐藏命令列，以及按真实工作阶段显示混流进度。
- Windows 170个源码文件散列与构建核对通过，冻结版与 Docker 最终 GUI 回归完成；中英文界面 wiki 共36幅实际截图已更新并验证发布。
- MyGO 自动布局仍为4.0、虚拟机 Vulkan 不可用、缺少真实混合 HDR 来源等情况按限制保留，不能表述为全部功能在所有环境下均无问题。覆盖审计索引为 `reports/final-coverage-audit.json`，包含14类功能和61份证据。

## 覆盖清单

| 项目 | 最终状态 | 主要证据与范围 |
| --- | --- | --- |
| Downloads 一级原盘 GUI、分集、SP、命名 | 30项完成授权范围 | `state/inputs.json`；Fullmetal 仅字幕合并 |
| U2/jsum 对照 | 已核对可获得资料 | 含 MyGO #63009、Bucchigiri；无同版参考的限制保留 |
| Remux、SP、完整评论轨 | 代表路径通过 | bd-saw、Re:Zero、Frieren 三集双提供者、独立音轨/图片、重名拦截、阶段提示 |
| ODDTAXI、Sonny Boy、循环菜单 | 用户指定操作通过 | 13个广播剧章节排除；BONUS取消主MPLS；三种循环实际媒体通过 |
| 缺失轨道和稀疏音频 | 沿用既有覆盖 | 按 SCOPE-03，9月3日已测且本轮核心路径未改，不重复完整矩阵 |
| Encode 编码器和音频 | 代表组合通过 | x264 8/10、x265 8/10/12、SVT-AV1 8/10；FLAC/AAC/Opus、音轨保留、软硬字幕 |
| DV、HDR10+、RPU、裁剪 | 适用流程通过 | 完整短素材；真实混合HDR来源缺失和不支持的位深明确保留 |
| VFR、非零起点、五项滤镜、预设 | 实际 GUI 和成品通过 | 360帧PTS精确相等、375毫秒起点、硬字幕窗口；预设增改删与直接覆盖；音频2毫秒工具层观察 |
| getnative / FrameCheck | 代表缺陷修复及实际回归通过 | 全样本支持度、空白帧与隐式色彩转换修复；30dB阈值保留，正常/阳性对照通过 |
| 字幕合并和编辑 | Linux/Windows及适用Docker功能通过 | ASS/SRT/SUP、大ASS、字体、64集混合ISO/目录、部分勾选和行身份 |
| 添加章节 | Linux/Docker/Windows通过 | 77集393章、独立输出和直接修改副本；原文件已恢复 |
| W64 / MyGO 3.1 | W64通过；MyGO布局暂缓 | theater PCM大于4GiB完整提取；MyGO全轨数据正确但自动仍4.0，3.1修正副本通过 |
| Linux / Docker / Windows | 适用媒体及最终GUI回归完成 | 42cf069最新Docker/Windows；Windows工具及多进程已验证，Vulkan/听感限制保留 |
| 中英文界面 wiki | 已发布并验证 | 两份文档、36张对应语言JPEG，`wiki-screenshot-publication.json` |
| 修改验证、提交与推送 | 完成 | 23个提交、远端9afd36d、工作区干净 |

## 执行记录

- GUI-01（INPUT-22 bd-saw）：GUI 加载四卷。原始字母序为 SPICE AND WOLF 2、SPICE AND WOLF 4、SPICE AND WOLF DISC 1、SPICY AND WOLF 3，默认分集共 13 集；完整输入检查及 U2/SP 对照仍待完成。
- GUI-02：新增 table1 勾选与拖动。将第 2 卷移到首位，嵌套 MPLS 表及命令跟随来源；取消该卷后正片由 13 集变为 10 集，EP 编号重排，SP 中排除该卷。截图保存于 `screenshots/bd-saw-reordered.png`、`bd-saw-unchecked-outputs.png`、`bd-saw-unchecked-sp.png`。
- FIX-01：首版 Qt 默认拖动清理会删除已移动源行，改用自管 QDrag 后 GUI 拖动通过。自动测试 94 项通过。
- FIX-02：电影模式部分勾选时使用压缩后的卷号，GUI 重现读取错误卷章节与时长。已改为 table1 实际卷号，等待重启验证；排序时输出编辑内容按 MPLS 来源移动，避免错配到其他卷。增加原有关键测试中的身份保持断言并通过。

- GUI-03：电影模式排除前两卷后保留第 3、4 卷，时长 01:35:24.010 / 01:11:33.039 与相应 MPLS 一致；手工命名 TEST_DISC_1.mkv 随 DISC 1 拖动到下一行，未套用到其他卷。
- GUI-04：所有卷取消后正片及 SP 表清空；点击开始弹出“未选择原盘主 mpls”，未启动媒体处理。列标题升降序切换正常。
- GUI-05：电影/剧集模式切换保留卷选择。切换 Remux/Encode 功能页会按原有逻辑清空输入，重新选源后继续，暂不扩大功能范围。
- CHECK-01：最终 94 项测试全部通过（0.401s），i18n、mixin 契约、UTF-8/CRLF（16 文件）、git diff --check 通过。验证日志 `logs/disc-selection-tests-final.log`。
- COMMIT-01：`bd76a4c` / `feat(gui): reorder and select Blu-ray discs`；已成功推送 origin/main（1c7eee0 → bd76a4c），工作区干净。

- U2-01：bd-saw 与 U2 #1309 散列值 b7e1b1f6227fbe2d0719e0e9665b4840aa7028d8 匹配。其它版本中无 jsum 标识，选用 THORA #4704 的 13 集 + OP/ED 文件表作参考，保存于 reports/bd-saw-reference.json。
- GUI-06：已按 DISC 1、SPICE AND WOLF 2、SPICY AND WOLF 3、SPICE AND WOLF 4 拖动排好卷序，13 集正片随顺序重新生成。输出设置为 Test-20260909/Remux，保留剪裁版权片段和 FLAC 转换。
- PREVIEW-01：Linux GUI 启动 mpv 成功并可退出。第一卷 00002.mpls（00029.m2ts）实际为菜单画面但默认勾选，已手动取消；第二卷 00002.mpls（00022.m2ts）预览为片头动画。音频听感未验证。

- REMUX-01：通过 GUI 启动 bd-saw 的 13 集及所选 SP 实际混流，输出 Test-20260909/Remux/bd-saw。已取消确认的菜单条目，并在 GUI 中把第二卷 OP/ED 分别命名为 SPs/OP.mkv、SPs/ED.mkv。已成功完成，产物验证见 REMUX-02。

- U2-03：整理了 23 组其它版本候选，读取并展开了 9 组参考文件表，加上 bd-saw 共 10 组；其中 7 组已确认发布者 jsum。文件表保存于 reports/u2-reference-file-lists.json。BanG Dream 剧场版暂只有前篇参考；新版舞-HiME/乙HiME盒装采用 QTS 全系列旧版作有限对照；其余暂缺 BDrip 参考的输入仍继续 GUI 检查。
- READ-01：初读 FrameCheck 实现：重新执行实际 Encode VPy，与成品按帧序号比较，默认亮度及色度阈值均 30 dB，任一适用平面低于阈值判 suspect。尚未进行本轮 Encode/FrameCheck 实测，不先修改算法或阈值。

- REMUX-02：宿主机 bd-saw 完成 13 集正片 + 13 个所选 SP，共 73.31 GiB。全部 MKV 可解析，正片卷序/EP 命名及每集 4 个章节、FLAC 音轨符合本轮选择；OP/ED 自定义命名生效。91 处片头、片尾和章节边界解码抽检全部通过，无残留临时目录。4 个 SP 的静音音轨被移除且逐项报告。详见 reports/bd-saw-remux-media.json、reports/bd-saw-decode-samples.json。默认菜单 SP 误选仍另行检查，不据此标记 SP 默认选择整体通过。
- DOCKER-01：执行 docker build -t bluray-subtitle-ubuntu . 成功，镜像 5244aef9d14f，源码 bd76a4c；独立 Xvfb :100/noVNC :6081 启动 Docker GUI，挂载 Downloads/Output/VideoAndSub 与独立配置目录。英文主窗口及 bd-saw 加载通过；GUI 播放 OP 并用 q 正常退出，mpv 日志 AO=pulse、VO=x11。听感未验证。截图 screenshots/docker-op-preview.png。
- PREP-04：Zootopia 2 ISO 已完整解压到原一级输入文件夹内的 Zootopia_2_2025_ULTRA_HD，7z 成功（1268 文件），原 ISO 保留。记录 state/zootopia-extraction.json。
- READ-02：Black Hawk Down 的主要候选是 00501/00502（约 144 分钟）与 00503/00504（约 152 分钟），每对视频时间线完全相同，两个版本共享约 83% 的较短版视频。Zootopia 2 的高分候选均 6464.833 秒。宿主机 GUI 当前 Black Hawk Down 仅默认选择 00502；正在实现电影双版本保守默认识别。

- GUI-07：Black Hawk Down 新默认选中两条主 MPLS，对应 02:24:18.649 和 02:31:50.601。GUI 回归发现同卷两个版本默认输出文件名重复，已修正为同卷多 MPLS 附加序号；重启后 GUI 验证为 Black Hawk Down - 4K Ultra HD_1.mkv / _2.mkv，独立命令和输出均对应两版本。证据 screenshots/black-hawk-two-outputs-fixed.png。Zootopia 2 GUI 对照继续。

- GUI-08：Zootopia 2 通过原一级输入目录加载，解压子目录作为该输入内的唯一卷；GUI 仅生成 00800 对应的一条 01:47:44.833 正片输出。证据 screenshots/zootopia-single-output.png。
- COMMIT-02：92b8efc / feat(gui): select alternate movie cuts by default，已成功推送 origin/main（bd76a4c → 92b8efc）。9 项针对性测试及编译、i18n、mixin 契约、UTF-8/CRLF（10 文件）、git diff --check 通过。文档与中英文历史同步更新。

- ENCODE-PREP-01：复用 bd-saw 的 EP01、EP05 和 OP，复制到独立 Fixtures/bd-saw-pair，避免章节/附件编辑影响 Remux 基准产物。通过 GUI 加载该目录，为三行指定独立 prefix360.vpy；仅在默认脚本最后加入 res.std.Trim(first=0, length=360)，其余处理保持默认。
- DOCKER-02：92b8efc 镜像重建完成（409daac23aae），现有容器仍为上一版，后续测试前替换。

- GUI-09（INPUT-02 Frieren S02）：新版 Docker GUI 加载 3 卷，默认主 MPLS 均 00002，分集 4＋3＋3 共 10 集；EP01–EP10 和分卷 SP 命名一致。34 行 SP 覆盖菜单、上映见面会、NCOP/NCED、迷你动画、PV/MV/预告，以及映射到 EP01/EP05/EP08 的评论音轨；与 jsum #65759 内容分组相符。22 秒 PV、短 Logo 和 IGS 默认不选，符合现有规则。第三卷两条附加 MPLS 均映射到 EP08；轨道窗口可打开并显示日语 PCM 轨。媒体附加回归另行执行。证据 screenshots/frieren-docker-*.png、reports/frieren-playlists.json。
- ENCODE-01：GUI 启动 x265 10-bit 均衡 CRF18、AAC、getnative、自动裁边、对比图、FrameCheck。EP01 已完成 360 帧，FrameCheck pass/0 可疑，最低 Y/U/V=45.17/50.12/51.65 dB；360 帧时间戳与来源逐帧完全一致，视频 15.015s，AAC 保留完整 1420.032s，4 个章节保留。报告 reports/encode-ep01-x265-aac-media.json 及输出 FrameCheck 目录。EP05/OP 继续执行。
- GETNATIVE-01：EP01 的 12 个样本中 11 个被判有效，7 个为 720p，但最终选择只有 1 个样本支持的 1024p。当前分组规则只累加每组最强 3 个权重，且高度四次方权重明显偏向高分辨率。还发现开头纯白帧（裁掉 5 像素边缘后标准差为 0）被判成有效 950p。已保存抽帧和逐核记录，继续对照 EP05/OP 后决定修复范围，不把所有差异直接归因于原盘。

- ENCODE-02：首组 x265/AAC 已全部成功完成（EP01、EP05、OP 各 360 帧），三份 FrameCheck 均 pass/0 可疑，Y 最低值分别为 45.17/45.45/45.03 dB。源码 GUI 的开始按钮恢复可用；对比图已生成，画面与其他产物验证继续。资源采样覆盖后续分集和 OP：进程 RSS 合计峰值 5.47 GiB，系统可用内存最低 8.85 GiB，未使用交换空间。
- COMMIT-03：3d5b512 / fix(getnative): retain all sample agreement and skip blank frames，已推送 origin/main（92b8efc → 3d5b512）。七项针对性测试、真实候选重算和纯白样本回放、i18n、mixin 契约、编译、UTF-8/CRLF（7 文件）、git diff --check 通过。新 GUI 回归继续；原 x265 运行使用启动时已加载的旧版逻辑作为基准。
- GUI-10（INPUT-03 Re:Zero S3）：五卷可加载，第一卷两条完整时间线相同的 90 分钟 MPLS 可用于整条附加测试。默认 24 分钟参数将加长首集切成四段；进一步发现加载后把参数改为 90 分钟不生效，代码在 GUI 重建时读固定默认值且未把该参数纳入变更判断。已修复，针对性测试 15 项通过（详见日志），正在 Docker 中回归实际界面。

- COMMIT-04：0be01c2 / fix(gui): apply edited episode duration when rebuilding outputs，已推送 origin/main（3d5b512 → 0be01c2）。Docker GUI 验证 24→90→24 分钟时重新分集：90 分钟生成五个整卷输出，24 分钟恢复 19 个分段；第一卷加长集需调整为完整 90:31.509。15 项相关测试、i18n、mixin 契约、编译、UTF-8/CRLF、git diff --check 通过。证据 screenshots/rezero-duration-90-fixed.png、rezero-duration-24-fixed.png。
- ENCODE-03：通过宿主机 GUI 启动第二组，EP01/EP05，x264 10-bit 均衡 CRF18、Opus、完整来源 getnative、自动裁边、对比图、FrameCheck；视频仍为 prefix360.vpy 的 360 帧。新逻辑已输出两条纯色画面跳过提示，后续结果待验证。

- COMMIT-05：3a74c81 / fix(encode): honor implicit H.264 limited color range，已推送 origin/main（0be01c2 → 3a74c81）。x264 的 --range tv 在其它视频信号字段均默认时可以省略 VUI；H.264 附录 E 规定缺失 video_full_range_flag 按 0/limited 推断。此前验证误报 unknown。真实成品和一帧显式 full 标记副本共四组检查通过，limited/full 真实不匹配仍报错；既有元数据测试 5 项、i18n、UTF-8/CRLF、编译、diff 检查通过。报告 reports/h264-range-verification-regression.json；标准 https://www.itu.int/rec/dologin_pub.asp?id=T-REC-H.264-202408-I%21%21PDF-E&lang=e&type=items 。当前两个已启动 GUI 仍使用 0be01c2 的已加载代码，后续启动再应用此修复。

- ENCODE-04：第二组 x264/Opus 完成两集，各 360 帧 H.264 High 10/yuv420p10le，Opus 保留完整约 23:40.022，4 个章节；360 帧 PTS 与来源逐帧完全相等。getnative 两集均为 720p/bicubic_0.0_0.5；FrameCheck 均 pass/0 可疑，Y 最低 44.58/44.81 dB。报告 reports/encode-x264-opus-media.json。两条元数据警告来自本批启动时尚未修复的 H.264 默认 limited 验证，修复已另行验证。
- RESUME-01：原配置再次点击开始压制，已有两集 MKV 的大小和修改时间未改变，GUI 成功结束；已有 Compare 图片的修改时间也未变化。恢复时仍重新扫描一次对比帧，记录为性能观察项。
- GUI-11：Re:Zero S3 可通过首行结束章节设为 ending，将第一卷变为完整 90:31.509，同时保留后续四卷 4+3+4+4 的正常分集，共 16 集；手工范围调整会在后续原盘勾选重建时重置，需要重新核对。首卷主选轨窗口同时展示 00001.mpls 的 PID4352 及 00002.mpls 的 PID4353 日语 PCM，视频不重复；SP 的整条匹配行默认不另行输出。
- REMUX-03：Docker GUI 0be01c2 开始 Re:Zero 首卷完整 90 分钟正片（两条音轨）和 7 个默认 SP 实际混流，输出 Remux/docker-rezero。采用本次已启动测试会话中的镜像；新提交仅修正 Encode 元数据验证，下次启动 Docker 更新镜像。媒体结果待验证。

- FRAMECHECK-01：在 GUI 生成的 x264 EP05 成品副本中，仅将第 120 帧（从 0 开始）反相，其余帧采用 FFV1 无损保存；以本次实际 VPy 的独立快照执行辅助检测。360 帧中准确定位且只标记这一帧，最低 Y/U/V=7.25/19.40/22.97 dB；未修改阈值。报告 reports/framecheck-positive-control.json。该辅助调用未传实际帧时间表，报告秒数使用容器名义帧率；正式 Encode 已传真实时间戳，不据此判断生产时间轴。正常样本仍主要为同一动画片头，尚不足以证明所有素材都不误报。

- REMUX-04：Docker Re:Zero 首卷完成 1 个完整正片和 7 个默认 SP；正片 5431.510s，H.264 + 两条日语 FLAC + 封面，7 个章节。两条全长音频解码到统一 PCM 后，分别与原盘 PCM 的 SHA-256 完全相同且两轨内容不同；无残留临时目录。报告 reports/rezero-first-volume-remux-media.json、rezero-full-audio-source-hash.json、rezero-full-audio-output-hash.json。视频抽检继续。SP07 的 MPLS 重复引用同一片段六次，界面时长 705.204s，实际输出单次片段 117.535s；先记录显示与输出时长的差异，继续核对其规则。

- GUI-12（INPUT-04 Shangri-La Frontier S02）：主机 3a74c81 GUI 加载 Vol3_D1/D2、Vol4_D1/D2 共四盘，主 MPLS 均 00000，6+6+7+6 共 25 集。全部正片行的范围、卷号和 EP01-EP25 文件名已逐屏检查；52 行 SP 中 31 个非主 MPLS 按大于 30 秒去重时长规则默认勾选，21 个 IGS 不勾选，分盘 SP 输出名互不重复。部分背景片段重复 200/300 次使 GUI MPLS 总时长达到约 3 小时 49 分钟，继续作为时长显示观察项。该输入无需重复一般 Remux。证据 screenshots/shangrila-*.png、reports/shangrila-playlists.json。
- REMUX-05：Re:Zero 首卷视频在 0/600/2000/4000/5429.5s 附近抽检。直接按 seek 返回次序比较时两处不一致，进一步保留源时间戳验证，确认 M2TS 与 MKV 的 seek 起点不同；相同时间戳处的解码帧哈希全部一致，两处分别验证 28/18 帧。其余三处 3 帧比较相等。证据 reports/rezero-video-seek-alignment.json，前一份原始抽检报告保留以记录排查经过。

- REMUX-06：Re:Zero 首卷 7 个 SP 的开头和结尾共 14 处各解码 3 帧，全部通过；完整主输出两条音轨的 SHA-256 已程序化核对一致。
- DOCKER-03：3a74c81 镜像重建成功（f5705ab4d022），旧 Docker GUI 通过界面关闭并正常退出，新建 3a74c81 容器供后续测试。日志 logs/docker-build-h264-range.log。
- SUB-PREP-01：VideoAndSub 的 11 个字幕/字体压缩包已提取到 Fixtures/subtitle-assets，原压缩包保留；资产目录均在 Docker 输出共享内。四月是你的谎言的 23 个 ASS 解压后合计约 1.59 GiB，最大的约 113.91 MiB，将用于合并字幕和多进程内存测试。索引 state/subtitle-assets.json。

- MERGE-01：宿主机 GUI 加载 Re:Zero S3 五卷和 16 集 SC 字幕，首集 90 分钟、后续 4+3+4+4 集自动匹配正确。生成 5 对共 10 个 .zh-Hans.ass，8,680 条事件数量正确，章节偏移误差小于 0.01s（ASS 厘秒精度），每对输出逐字节一致。重复点击生成明确报已有输出且所有文件大小/修改时间/散列值不变。原版逐字检查发现正文逗号后及首尾空格被误删，已归档本次创建的旧产物以回归。报告 reports/rezero-ass-merge-validation.json。
- EDIT-01：独立 ReZero-52.CHS.ass 副本通过 GUI 排序、选中并批量删除原始第 1/2 行，事件 497→495；原始第 3 行的 Start/End、Layer、Name、Text 编辑及保存均与指定值一致，无残留临时文件。报告 reports/ass-editor-validation.json；截图 screenshots/ass-editor-bulk-delete-fields.png。
- COMMIT-06：13405ce / fix(subtitles): preserve ASS text whitespace when parsing，已成功推送 origin/main（3a74c81→13405ce）。ASS 事件仅拆分结构字段，正文保留逗号和全部空白；字幕右键“编辑字幕”使用已有中英文翻译。16 个真实 ASS 共 8,680 条事件的读写全文一致，7 项既有合并测试、i18n、mixin 契约、编译、UTF-8/CRLF、diff 检查通过。宿主机已重启该版本，GUI 合并回归继续。

- MERGE-02：宿主机 13405ce GUI 重新合并相同 Re:Zero S3 输入，16 个来源、五卷共 8,680 条事件的全文及全部字段匹配，时间偏移在 ASS 厘秒精度内，五对输出逐字节一致；此前 47 处正文空白差异全部消除。报告 reports/rezero-ass-merge-validation-fixed.json。
- SUP-PREP-01：使用项目 ass2sup.py 和 Re:Zero 配套字体目录，4 进程转换 16 集完整 ASS（包含 90 分钟首集）为 SUP，全数成功。另取 Break Time 51 在有/无配套字体两种条件下转换，实际 PNG 显示雅宋与系统回退无衬线字形差异，中文字形和描边正常；fc-scan 确认配套 FZZCYSK.TTF 的族名匹配 FZYaSong-DB1-GBK。报告 reports/ass2sup-rezero-main.json、reports/ass2sup-font-comparison.json，图像 Fixtures/font-comparison。

- MERGE-03：宿主机 13405ce GUI 加载完整 16 集 SUP，章节匹配与 ASS 一致，生成五对共 10 个 .zh-Hans.sup。逐包独立验证 73,337 个 PGS 包的 PTS/DTS 均按界面偏移量准确调整，其余包头/图像负载与来源逐字节一致；每卷两份输出相同。报告 reports/rezero-sup-merge-validation.json。

- MERGE-04（INPUT-18 四月是你的谎言）：宿主机 GUI 加载九卷原盘和 23 个 ASS，取消无对应蓝光原盘的 OAD，22 集按 1+2+2+2+3+3+3+3+3 匹配。来源合计 1,670,225,287 字节，首次生成 18 个文件共约 3.10 GiB。独立核对前五卷通过，在第六卷第 13 集发现同名样式复用错误：应引用 Alignment=8 的 Tips - sp1，却用了 Alignment=7 的 Tips - sp。18 个本轮旧产物已按散列值归档到 Fixtures/shigatsu-merge-before-style-fix，原字幕和压缩包保留。报告 reports/shigatsu-ass-style-conflict-before.json。
- PERF-01：大字幕首次加载的进程 PSS 合计峰值约 8.14 GiB，合并约 8.60 GiB，系统可用内存最低约 2.77 GiB、交换使用为 0；RSS 合计包含 fork 共享页，不能作为独占内存。原取消 OAD 勾选操作同步重新解析全部 22 个字幕，耗用约 18.3 秒 CPU，主进程 RSS 达约 4.36 GiB。改为复用表格已测量的字幕时长后，同一 GUI 操作仅增加约 0.09 秒 CPU，RSS 约 394 MiB；路径排序升降序及恢复正常，无大文件重解析。缺少某个时长时仍只读取该文件。报告 reports/shigatsu-subtitles-resources.json、subtitle-duration-reuse-regression.json、shigatsu-fixed-uncheck-resources.json。
- FIX-03：大字幕章节下拉回归暴露跨卷匹配错误。旧逻辑仅使用章号，相邻卷的第 1 章被当作同一来源，导致分配错卷并发生 IndexError，界面留下新章号与旧偏移。已同时传递 GUI 捕获的 MPLS 来源和章号，并正确处理最后一个字幕。九卷真实 MPLS 辅助验证及 22 集 GUI 回归通过：第 13 集改为第 10 章时偏移 44:14.026，恢复第 11 章后 45:46.077，其他集的卷号、章号、偏移不变。报告 reports/shigatsu-chapter-change-before.json、shigatsu-chapter-change-fixed.json；截图 screenshots/shigatsu-chapter-change-22-fixed.png。
- MERGE-05：宿主机 GUI 完成修复后的 22 集大 ASS 合并，生成九对共 18 个 .chs_jpn.ass。独立流式验证全部 5,657,170 条事件的正文和字段一致，时间偏移误差小于 0.01s，样式定义属性保持正确，九对输出 SHA-256 相同；第六卷第 13 集样式复用错误消除。报告 reports/shigatsu-ass-merge-validation-fixed.json。

- COMMIT-07：1294224 / fix(subtitles): preserve merge mappings and avoid repeated parsing，已提交并推送 origin/main（13405ce→1294224）。字幕时长复用、跨 MPLS 章节身份、ASS 样式复用一并修复；14 项既有相关测试、真实 MPLS 边界和大 ASS 全量验证、i18n、mixin 契约、编译、UTF-8/CRLF、diff 检查通过。当前宿主机运行源码与提交逐文件散列值相同。

- GUI-13（INPUT-06 柚木家的四兄弟）：1294224 宿主机 GUI 加载四卷，主 MPLS 均为 00000，4+2+4+2 共 12 集，完整核对 EP01–EP12 的卷号、章节范围、时长和默认命名。34 行 SP 中 13 行选中：9 个独立输出及分别附加到 EP01/EP01/EP07/EP12 的 4 行；8 个短片及 13 个 IGS 默认不选。菜单重复 300 次造成约 5 小时的显示时长，按已有观察项记录。U2 源散列已匹配，无其他版本候选；本输入不重复一般 Remux，继续配套 SRT 合并。证据 screenshots/yuzuki-*.png、reports/yuzuki-playlists.json。

- MERGE-06：柚木家的四兄弟 12 个 SRT 首次 GUI 合并生成四对文件，3,722 条正文与章节偏移均正确，但来源含编号 0 的元数据条目，跨集相加后产生 8 处重复编号。独立编辑回归确认：删除一条重复编号记录时，旧保存逻辑同时删除了另一条同号记录；编辑也可能定位错误。旧合并产物与编辑副本已归档，原始字幕保留。
- EDIT-02：改为在表格中保存原始行身份，ASS/SRT 编辑、排序、单行及批量删除均按该身份执行；SRT 保存时连续编号。真实 SRT 四条记录的重复编号编辑、单删、排序后批删均通过，未选中的同号记录不受影响；ASS 497→495 条的排序后删除和 Name 编辑也逐字段验证通过。报告 reports/srt-editor-row-identity-fixed.json、ass-editor-row-identity-fixed.json。
- MERGE-07：最新源码 GUI 重新合并柚木 12 集 SRT，四对输出全部通过独立验证：3,722 条正文逐字一致，时间偏移在毫秒精度内，每卷编号 1..N 连续且不重复，配对输出字节一致。报告 reports/yuzuki-srt-merge-validation-fixed.json。
- COMMIT-08：55996f1 / fix(subtitles): preserve editor row identity and renumber SRT cues，已提交并推送 origin/main（1294224→55996f1）。两文件变更，既有合并测试 7 项、i18n、mixin 契约、编译、UTF-8/CRLF、diff 检查通过，GUI 运行源码散列一致。无新增测试文件或普通修复历史条目。
- UI-OBS-01：字幕编辑测试后先加载字幕、再加载原盘，匹配列未自动刷新；取消并恢复第一条字幕勾选后立即恢复正确的 12 集匹配。按待复核的界面刷新观察项记录，尚未扩大修改。

- CHAPTER-PREP-01：按测试流程授权，将三部 AI-Raws 的 77 集正片分别移动到 Fixtures/add-chapters 的独立输入目录（Dark Gathering 25、迷宫饭 24、芙莉莲 28）。移动前路径、大小、修改时间记录在 state/add-chapters-move-manifest.json；77 个原 MKV 均无章节，媒体预检保存在 reports/add-chapters-before.json。计划完成后将原文件移回；独立输出保留。
- CHAPTER-01：Docker 55996f1 加载仅有 MPLS 的原盘目录时没有默认主播放列表。原因是添加章节仍以缺失的 M2TS 文件大小评分，所有分数为零。将字幕合并已有的“仅 MPLS”识别条件同时用于添加章节；三部作品 17 卷辅助验证均选中一个正确主 MPLS。章节未完整匹配时确实在创建任何输出前停止，记录了保护行为截图。
- CHAPTER-02：宿主机修复后自动选中迷宫饭四卷 00001，按界面顺序将 24 集独立混流到 input/output。全部 95 个章节时间与原盘对应、误差小于 0.00101 秒，轨道编码/格式和时长保持一致。报告 reports/chapters-delicious-in-dungeon-validation.json。Dark Gathering 的 Docker 同版本写入回归已启动；原文件直接编辑模式仍待覆盖。
- COMMIT-09：4283b5a / fix(gui): select main playlists for MPLS-only chapter sources，已提交并推送 origin/main（55996f1→4283b5a）。一行条件修复，4 项既有章节/卷选择测试、17 卷真实 MPLS 选择、24 集 GUI 写入与逐章节验证、i18n、mixin 契约、编译、UTF-8/CRLF、diff 检查通过。
- DOCKER-04：Docker 在本轮先构建 55996f1，发现 MPLS-only 选择问题后再次构建；当前镜像 8641607dc03e、容器 bluray-subtitle-gui-test-20260909-mpls-main 与提交 4283b5a 源码一致，实际文件散列已核对。构建日志 logs/docker-build-mpls-only-main.log。

- CHAPTER-03：Docker 同版本完成 Dark Gathering 25 集独立输出，全部 133 个章节核对通过；随后对这 25 个本轮输出副本使用“直接编辑原文件”模式，全部修改时间更新，再次核对 133 个章节通过。报告 reports/chapters-dark-gathering-separate-output-validation.json、chapters-dark-inplace-validation.json；截图 screenshots/chapters-dark-inplace-complete.png。
- CHAPTER-04：宿主机完成芙莉莲 28 集独立输出，165 个章节全部核对通过。三部共 77 集、393 个章节，轨道编码/格式和时长检查通过。报告 reports/chapters-frieren-validation.json；截图 screenshots/chapters-frieren-complete.png。
- MEDIA-CHAPTER-01：迷宫饭首尾两集共 72,336 个视频包的 PTS/DTS 逐包一致；关键帧附近的完整包散列变化来自 mkvmerge 插入 VPS/SPS/PPS 和附加信息。保留全部编码画面 NAL 后，两集完整 VCL 散列均与来源相同；首集两条完整 FLAC 音轨散列也分别相同。未发现画面内容变化，不作为视频问题修改。报告 reports/chapters-delicious-media-validation.json、chapters-delicious-vcl-hashes.json、chapters-delicious-header-insertion.json。
- CHAPTER-CLEANUP-01：核对 77 个临时输入的大小和修改时间均与移动前相同后，已全部移回原 VideoAndSub 路径；任务生成的章节输出保留在 Fixtures/add-chapters 各组 input/output 内。报告 reports/add-chapters-originals-restored.json。

- HDR-PREP-01：预检六部 UHD 输入的 72 个较小 M2TS，逐个读取轨道、时长及 24 帧侧数据；未发现 HDR10+。进一步读取这六部的 914 个 MPLS，HDRPlusFlag 均未置位，无解析失败。这不是完整 HEVC 全流缺失证明；当前短候选不足以验证真实 HDR10+ 全流程，继续检查 Dolby Vision，HDR10+ 暂按素材待补记录。报告 reports/hdr-short-candidates-probe.json、hdr-short-candidates-frame-probe.json、uhd-hdrplus-playlist-flags.json。
- HDR-PREP-02：Minecraft 00000.m2ts / 00000.mpls 是带完整 TrueHD 音轨的 15.5572 秒 WB 片头。独立提取完整基础层、增强层及 RPU，确认 373 帧 Profile 7 FEL、CM v2.9；基础层未含 HDR10+。已目视检查第 5 秒画面。作为 Docker Dolby Vision Remux 和后续 Encode 的短实盘素材。报告 reports/hdr-minecraft-logo-rpu-summary.txt，任务副本 Fixtures/hdr-minecraft-logo。
- ENCODE-AV1-01：宿主机 GUI 启动 bd-saw EP01、EP05 和 OP 三行 SVT-AV1 8-bit、preset 4 / CRF 20、AAC 256 kbps 测试，分别使用独立 360 帧 VPy，启用完整来源 getnative、裁剪、对比图和 FrameCheck。输出 Encode/svt8-aac256，结果待验证。首次启动因输出目录不存在被预检查阻止；创建目录后重新启动，未产生部分媒体文件。

- ENCODE-AV1-02：SVT-AV1 8-bit 三行 GUI 压制全部成功；三份 FrameCheck 均为 pass，各 360 帧、0 suspect，最低亮度 PSNR 分别 44.12、44.13、44.22 dB。独立解码检查 1,080 帧 PTS 与来源开头逐帧完全一致。两集视频为 1920×1080，OP 自动裁去左侧 2 像素后为 1918×1080。完整 AAC 256 kbps 音轨从零开始，解码采样数只多出 816/816/800 个样本（均不足一个 AAC 帧的填充），章节时间保持一致；未发现帧错配或截断音频。已目视检查首集第 180 帧对比图。报告 reports/svt8-media-validation.json，应用报告位于 Encode/svt8-aac256/bd-saw-pair/FrameCheck。
- GUI-14（INPUT-19 Minecraft）：Docker 电影模式加载一级原盘目录，仅默认选择 00800，正片 01:40:54.840、A Minecraft Movie.mkv。42 行 SP 完整查看，23 行默认选中为 SP01–SP23；较短内容及已覆盖正片的备用列表不选。相同 SP 视频的多条 MPLS 暴露不同字幕 STN，按电影 SP 独立输出的现有规则记录。
- HDR-REMUX-01：Docker GUI 仅选择 00000.mpls 为正片，取消全部 26 个其他 SP，保留基础层、Dolby Vision 增强层及英文 TrueHD；输出名称按 GUI 的 minecraft-logo-p7.mkv 执行。373 帧 Profile 7 FEL RPU 与来源逐字节相同；完整基础层 VCL、增强层 VCL 和 TrueHD 编码负载散列分别一致。报告 reports/minecraft-logo-remux-validation.json。
- HDR-PREP-03：Zootopia 2 的 00105.m2ts 为完整 360 帧短场景，含 TrueHD/PGS 和 Profile 7 FEL RPU，L5 上下各 276 像素。基础层完整严格解码无错误，增强层独立探测的引用警告不作为基础层或应用错误。使用外部 mkvmerge 混流选定视频、英文 TrueHD/PGS 作为 Encode 素材，RPU 全量字节一致。该操作仅为输入素材准备，不计为应用 Remux 回归。报告 reports/zootopia-short-fixture-validation.json。

- HDR-FIX-01：两段 P7 FEL 短素材通过 Docker GUI 以 x265 12-bit、原生 RPU 参数执行，均报 Main10-only 并以 code 3 停止；批处理正确继续第二行并汇总 2 个失败，没有发布最终 MKV。保留的 Zootopia RPU 已从上下 276 裁为 0，360 帧仍完整，但成品尚未验证。报告 reports/x26512-dovi-before-fix.json。
- HDR-FIX-02：对照 Dolby 官方 Profile 8 基础层 Main10 规定和 x265 4.3 实际错误，将 Dolby Vision 保留条件修正为 x265 10-bit，更新中英文提示、README 和编码 wiki。8 项既有元数据/Dolby Vision 测试、两段真实 MKV 的 7 组预检查、i18n、编译与 UTF-8/CRLF/diff 检查通过。Docker 候选镜像已构建并确认两文件与宿主机源码字节一致，GUI 回归继续；尚未提交。

- HDR-FIX-03：新 Docker GUI 加载两段真实 P7 MKV，选择 x265 12-bit 后点击开始，立即显示“Dolby Vision preservation requires x265 with 10-bit output”；原 17 个诊断文件的大小与修改时间完全不变，没有启动编码或生成新产物。截图 screenshots/dovi-main10-preflight-fixed-en.png，报告 reports/dovi-preflight-gui-files-unchanged.json。
- COMMIT-10：d63a6a5 / fix(encode): require Main10 for Dolby Vision preservation，6 个文件的修复和中英文说明更新已提交并推送（4283b5a→d63a6a5）。8 项既有相关测试、实际来源预检查、Docker GUI 提前拦截、i18n、编译与 UTF-8/CRLF/diff 检查通过。当前 Docker 运行源码与提交一致。

- HDR-ENCODE-01：Docker d63a6a5 通过 GUI 完成两段 x265 10-bit 原生 Dolby Vision 压制：Minecraft 373 帧 / 3840×2160，Zootopia 360 帧 / 3840×1608。两者均为 Profile 8.1（compatibility id 1，EL=0）；全部视频 PTS 与对应来源逐帧相同，静态色彩字段一致，完整 TrueHD 音轨保留且解码 PCM 散列相同。逐帧核对 733 份 RPU 显示管理数据：Minecraft 全部保持一致；Zootopia 360 帧仅将 L5 上下偏移由 276 改为 0，其他 DM 字段不变。已目视查看同帧裁剪前后图。报告 reports/x26510-dovi-crop-media-validation.json。
- FRAMECHECK-02：上述 Minecraft 成品在旧 FrameCheck 被标记 147 帧 suspect。实测基础层、VPy 输出和成品首帧亮度值全为 0，但 Y4M 不携带完整色彩标签，FFmpeg 自动在成品侧插入 bt2020nc→unknown 的 RGB 中间转换，将黑电平抬到 64，错误得到 Y PSNR 24.07 dB。逐帧信息表明问题集中于首尾黑场/渐变。原始报告保留，诊断见 reports/minecraft-psnr-oneframe-variants.json、minecraft-dv-raw-black-level.json、minecraft-dv-vpy-black-level.txt。
- FRAMECHECK-03：在比较入口仅统一范围与矩阵标签，防止隐式颜色转换，直接比较编码样本。使用同一份未重新编码的 Minecraft 成品，完整 373 帧复核为 pass/0 suspect，最低 Y=55.13 dB；既有单帧反相阳性对照仍且只识别第 120 帧，最低 Y=7.25 dB。30 dB 阈值保持不变。1 项既有 FrameCheck 测试、实际媒体辅助回归、编译、i18n、UTF-8/CRLF 和 diff 检查通过。报告 reports/framecheck-neutral-regression.json；本次仅修正既有检测行为，不新增测试文件或普通修复历史。
- COMMIT-11：2d93059 / fix(framecheck): compare samples without color conversion，单文件修复已提交并推送（d63a6a5→2d93059）。Docker 修复镜像已构建，接下来通过 GUI 验证独立 Main12 HDR 编码与新 FrameCheck 的集成。

- HDR-ENCODE-02：Docker 2d93059 通过 GUI 完成独立 Main12 HDR 基础层编码。373 帧均严格解码通过，实际像素格式 yuv420p12le，全部 PTS 与来源完全相等；BT.2020/PQ、Mastering Display 和 MaxCLL 元数据保持一致。完整 TrueHD 音轨解码 PCM 散列与来源相同。GUI 集成 FrameCheck 为 pass/0 suspect，最低 Y=54.95 dB；未改变 30 dB 阈值。报告 reports/x26512-hdr-base-media-validation.json，截图 screenshots/x26512-hdr-base-completed.png。

- GUI-15（INPUT-09 Tsuyokute New Saga）：Host 2d93059 加载一级文件夹，两卷主 MPLS 均为 00001，6＋6 共 12 集；每行章节范围、卷号与 EP01–EP12 命名已查看。16 行 SP 中 10 行默认勾选，包括 4 个视频、6 个 PNG 静态图片；4 个短片与 2 个 IGS 不选，分卷输出名称无重复。截图 screenshots/tsuyokute-*.png。继续实际静态图片导出，不重复一般视频 Remux。

- SP-ONLY-01：GUI 取消全部主 MPLS、仅保留六个已命名 PNG SP 后，启动被“未选择原盘主 mpls”阻止，未生成媒体。代码复核确认 SP 已有独立计划与执行管线，但 GUI 和主任务计划均无条件要求正片。按可见选择的执行契约调整为允许仅 Remux SP，补充中英文 README 操作说明。18 项既有 Remux/SP 测试、六个真实 MPLS 的只读计划及五类空/不一致请求检查、i18n、mixin、编译、UTF-8/CRLF、diff 检查通过；Docker 已重建，宿主机 GUI 回归中，尚未提交。报告 reports/sp-only-preflight-regression.json。

- SP-ONLY-02：Host 修复版本通过 GUI 完成六个 PNG SP，均为 1920×1080。独立将各原始 M2TS 首帧解码为 RGB，与对应 PNG 全部像素逐字节一致；已目视检查菜单图。相同 GUI 请求再次执行时明确报输出已存在，六个文件大小和修改时间不变。报告 reports/tsuyokute-still-sp-validation.json。
- COMMIT-12：0307bcd / fix(remux): allow selected SPs without main playlists，四文件修复和中英文操作说明已提交推送（2d93059→0307bcd）。18 项既有相关测试、真实来源计划、GUI 实际 PNG 输出和冲突保护、i18n、mixin、编译及编码/换行/diff 检查通过。当前宿主机运行源码与提交一致；Docker 新镜像已构建，旧 GUI 容器仍使用 2d93059。

- SP-IMAGE-01：Host 0307bcd 通过 GUI 单独选择两卷 00007.m2ts 的 IGS 菜单，输出到 Remux/tsuyokute-igs。每卷生成 selected/activated 的 start/stop 四个状态，共八张 1920×1080 RGBA PNG；图片均有效且非全黑。目视核对第一卷激活状态的文字、位置与独立静态菜单背景一致。报告 reports/tsuyokute-igs-validation.json。
- SP-ONLY-03：GUI 取消全部主 MPLS 和 SP 后，启动在捕获阶段提示“任务配置不能为空”，既有六张图片不变。截图 screenshots/sp-only-empty-request-blocked.png。

- GUI-16（INPUT-13 Kaijuu 8 Gou S2）：Host 0307bcd 从一级目录加载第 5–8 卷，四卷主 MPLS 均为 00002，2＋3＋3＋3 共 11 集。全部正片章节范围、M2TS、卷号、EP01–EP11 命名已检查。逐屏检查 77 行 SP，默认选中 56 行（14/13/15/14），含分别附加 EP05/EP07/EP09 的三行；其余 53 个独立 SP 路径无重复。13 个 IGS 和 8 个短片默认不选。U2 #63847 的已保存其他版本候选为空；不重复一般 Remux。截图 screenshots/kaijuu-*.png。

- GUI-17（INPUT-16 Violet Evergarden，进行中）：从一级目录一次加载八卷。jsum #31680 文件表确认普通卷包含 TV 01–13 和 Extra EP14，SPECIAL 四卷分别收录 EP01–03/04–07/08–10/11–13 剧场上映版。通过 GUI 键盘选择取消四个 SPECIAL 卷，控件禁用、普通卷命令保留。正在核对普通卷分集/SP，之后单独选 SPECIAL 切电影模式。截图 screenshots/violet-series-select-*.png。
- DOCKER-05：Main12 回归容器在完成后通过 GUI 正常退出（exit 0），日志保存在 logs/docker-x26512-hdr-base.log；相关浏览器页已关闭。修复 SP-only 后的新镜像已构建，对应 0307bcd，待下一轮 Docker 启动使用。

- GUI-18（INPUT-16 Violet 完成）：普通卷选择 1/3/5/7，生成 3＋4＋3＋4 共 14 集；全部名称与章节行、58 行 SP 已查看。默认 32 个 SP 选中（8/8/7/9），24 个 IGS 与两条 16 秒广告不选。拖动普通卷 2 到第 2 行后，EP04–EP07 和主命令的 BD_Vol_003 正确变为 BD_Vol_002；勾选与主 MPLS 保持。点击路径表头恢复升序时选择状态保持。
- GUI-19（Violet SPECIAL）：只选择 2/4/6/8 四张 SPECIAL 盘，切电影模式后生成四个完整输出，分别 01:15:06.627、01:32:58.573、01:14:58.494、01:13:24.400；均为 00000 主 MPLS。28 行 SP 全部查看，16 个默认选中、12 个 IGS 不选，名称与卷号正确。两组均对应 jsum 文件表的 TV/Extra 与四个 Theater Ver. 分类；不重复一般 Remux。报告 reports/violet-gui-validation.json，截图 screenshots/violet-*.png。

- GUI-20（INPUT-08 MyGo Movie）：Host 0307bcd 电影模式从一级目录加载前后篇两卷，分别仅选择 00000，生成两个完整输出 01:58:21.094 / 01:59:59.192。片名读取原盘元数据，前／后篇标题及 BD_Vol_001/002 不重复。8 行 SP 均已查看，4 个 9/5 秒短片和 4 个 IGS 默认不选。已保存 BDB_Raws #63017 参考只覆盖前篇；不重复一般 Remux。截图 screenshots/mygo-*.png。

- GUI-21（INPUT-25 Inside Out 2）：Host 0307bcd 电影模式仅选 00800，单个完整输出 01:36:25.612；默认片名来自原盘元数据。逐屏检查全部 296 行 SP（295 条非主 MPLS＋1 个未覆盖短视频），27 行选中，SP01–SP27 无重名。01476 仅 20.020 秒但包含多个不同片段，符合短内容例外。00805 是默认选中的约 96 分钟备用完整列表，按近似重复默认策略待复核观察项记录，未据此修改算法或实际输出完整重复影片。截图 screenshots/inside-out2-*.png。
- HDR-SOURCE-02：Kodi 官方测试页列出公开混合样片，但其 MEGA 地址被浏览器站点策略明确禁止访问（未发起用户权限提示或自动审批），没有通过其它方式获取同一文件。FF Pictures 的公开 Lake HDR10+ 测试下载链接被网页工具标记为不安全的跳转，同样未绕过。
- HDR-PREP-04：改用 hdr10plus_tool 上游 GitHub 公开测试素材 regular.mkv 与 regular_metadata.json。MKV 为 256×144、259 帧、10.803 秒、仅视频；全部帧严格探测无错误且均有 SMPTE ST 2094-40 HDR10+，参考 JSON 也有 259 帧 SceneInfo。该素材用于完整短文件的动态元数据流程验证，不冒充 4K 原盘或 DV/HDR10+ 混合样片。文件 SHA-256、来源 URL 和探测报告保存在 reports/hdr10plus-upstream-fixture-probe.json；已准备完整来源的 10/12-bit VPy 和独立空输出目录，尚未运行 GUI Encode。

- HDR-ENCODE-03：Host 0307bcd 通过 GUI 完成 hdr10plus_tool 上游完整短素材的 x265 10-bit 与 12-bit 原生 HDR10+ 压制。两个成品分别为 yuv420p10le / yuv420p12le；共 518 帧 PTS 与来源逐帧一致，逐帧 SceneInfo 与来源完全相等，来源 SceneInfo 也与上游参考 JSON 相等。两份 FrameCheck 均为 pass/259 帧/0 suspect。该全黑 256×144 测试素材验证元数据流程，不代表真实 4K 画质或 DV/HDR10+ 混合来源。报告 reports/hdr10plus-x265-10-validation.json、hdr10plus-x265-12-validation.json，截图 screenshots/hdr10plus-*.png。
- LOG-FIX-01：上述 GUI 测试发现，中文“自动生成的编码器元数据参数”日志被二次翻译，使 --dhdr10-info、路径中的 Encode 和部分参数括号被改写；实际启动命令与成品元数据正确。对该已翻译模板的终端输出增加保留字面量选项，其他日志继续默认翻译。3 项既有元数据测试、英/中文实际参数诊断、i18n、编译与 CRLF/diff 检查通过，Docker 已构建；已重启 Host GUI，执行独立日志回归后提交。

- LOG-FIX-02 / COMMIT-13：ee25b33 / fix(encode): preserve literal metadata arguments in logs，两个文件的修复已提交并推送 origin/main（0307bcd→ee25b33）。Host GUI 完成 259 帧独立回归，中文自动参数日志与实际启动命令中的参数逐字一致，--dhdr10-info、Encode 路径及参数括号完整保留；未改其他日志的默认翻译。报告 reports/metadata-log-preservation-regression.json，截图 screenshots/metadata-log-regression-*.png。

- GUI-22（INPUT-05 Tiramisu S2）：Host ee25b33 从一级目录加载 Disc 1/2，两卷主 MPLS 均为 00001。通过 GUI 将每集时长由 24 改为 7 分钟，正确生成 6＋7 共 13 集；EP01–EP13 及章节边界、卷号、末行 ending 全部查看。22 行 SP 全部核对，默认选中 10 行（六个视频、四个 PNG），四个短片和八个 IGS 不选。各卷 SP01–SP05 唯一。已保存 U2 #64294 候选为空，不重复一般 Remux。截图 screenshots/tiramisu-*.png。

- GUI-FIX-03 / COMMIT-14：68fc10a / fix(gui): restore disc options after Remux-source encode，修复从“压制→Remux 输入”切回“原盘 Remux”时版权裁剪与 Dolby Vision 选项仍隐藏的问题。四行显示恢复，已提交并推送 origin/main（ee25b33→68fc10a），；GUI 实测先取消版权裁剪、保留 Dolby Vision，再切换输入/功能，两控件正确隐藏与恢复，勾选状态不变且可继续点击。mixin 契约、编译、UTF-8/CRLF/diff 检查通过，Docker 已重建；本次仅恢复既有操作，不增加产品文档或历史。报告 reports/remux-controls-switch-regression.json。
- GUI-23（INPUT-01 Coji Coji，进行中）：从 Tiramisu 切换输入后看到分集表残留前作四行，Coji 第一卷主列表和 SP 已部分显示。未执行输出，已保存 screenshots/coji-after-source-switch-stale-episodes.png；使用新进程重新载入同一一级目录，以核对是否为可复现的输入状态问题。

- GUI-24（INPUT-01 Coji Coji）：Host 68fc10a 新进程一次加载全部四卷，各选 00000 主 MPLS；101 行分集逐页核对，卷数为 26＋25＋25＋25，章节边界、EP001–EP101 与 BD_Vol_001–004 名称正确。126 行 SP 全部查看，101 个与单集内容相同的 MPLS 不选；默认选中 9 行（1/4/1/3，其中四个单帧 PNG、五个视频），八个短片、四个 audio_only、四个 IGS 不选。文件名无重复，未执行多余全盘 Remux。截图 screenshots/coji-episodes-01..05.png、coji-sp-01..06.png 及 coji-volumes-*.png。

- GUI-25（输入切换复查）：在同一 Host 68fc10a 进程通过 GUI 再次加载 Tiramisu、7→24 分钟调整后切回 Coji。当前分集表正确变为 Coji，旧四行未残留；保留最初一次观察，不据此新增推测性修复或继续扩大调查。截图 screenshots/coji-source-switch-replay-passed.png。

- GUI-26（INPUT-15 Dai Nana Ouji S2，进行中）：Host 68fc10a 加载两卷 Vol.1/BD、Vol.2/BD，主 MPLS 均为 00001，6＋6 共 12 集的章节与命名已检查，版权裁剪反映在 --split parts 命令。SP 中两条独立音频 00013.m2ts 默认勾选但输出名为空，打开轨道窗口确认编号 0 未选。
- TRACK-FIX-01：真实 M2TS 音轨 index=0，被默认选轨中的真值判断误当空值并过滤；同类问题也影响纯字幕或第一条音轨。入口将有效轨道编号统一为字符串，保留原始输入不变。两段真实 PCM 来源修复后均默认选择 [0]；英/中文、第一条额外音轨、纯字幕、按 index 映射语言五类辅助检查通过，27 项既有相关测试、mixin、i18n、编译、UTF-8/CRLF/diff 检查通过，Docker 已构建。手动选轨可正确生成 .flac，当前重启 GUI 进行默认选择及实际音频导出回归；尚未提交。

- TRACK-FIX-02：修复后的 GUI 两卷独立音轨均自动选中编号 0，分别生成 BD_Vol_001_00013.flac 和 BD_Vol_002_00013.flac。默认 23 行 SP 已全部核对：17 行选中，其中四行附加 EP01/03/07/09、两个 PNG、两个独立音频，六个 IGS 不选。
- AUDIO-SP-01：仅保留两条独立音频，通过 GUI 执行后首行失败；FFmpeg 明确报 PCM 不能直接复制到 FLAC 容器。Remux 调用漏传单独音频目标格式，Encode 路径已有该参数。已将计划为 .flac 的单音轨 SP 显式传给转换器，输出目录没有残留文件，仍使用同一路径重新验证。错误日志 logs/host-app-zero-index.log，截图 screenshots/dainana-audio-flac-copy-error.png。

- AUDIO-SP-02：同一输出目录通过 Host GUI 成功导出两段独立 FLAC。48000 Hz 双声道，每声道分别 5,621,520 与 8,456,400 个样本；完整解码为 PCM s32le 后，字节数与 SHA-256 均与原始 M2TS 完全相等，无解码错误。报告 reports/dainana-audio-only-validation.json。
- COMMIT-15：6f11ff8 / fix(remux): select and convert standalone audio tracks，两个文件、14 行增加／1 行删除，已提交并推送 origin/main（68fc10a→6f11ff8）。修复默认选轨丢失 index=0 及独立 FLAC 未转换；两组相关既有测试分别 27/18 项通过，真实来源与五类编号诊断、GUI 默认选择和完整音频产物核对、mixin/i18n/编译/UTF-8/CRLF/diff 通过。Docker 已构建，Host 源码与提交一致。

- WIN-PLAY-01：Windows GUI 从 EP01 的播放按钮打开播放器，真实视频画面正常。q 未使窗口退出，随后点击播放画面并 Alt+F4 正常关闭，返回应用；不更改用户播放器绑定，音频听感未验证。截图 screenshots/windows-mpv-playback.png。
- WIN-ENCODE-01：Windows GUI 6f11ff8 加载既有 bd-saw-pair 两集与 SP/OP，为三行选择由 Windows 默认模板准备的独立 VPy（仅输出深度 8 和末尾 360 帧测试裁切）。x264 8-bit、Balanced medium/CRF18、AAC 256 kbps，保留完整来源 getnative／音频、裁剪、对比图和 FrameCheck。GUI 已启动，输出 Encode/windows-x2648-aac256；getnative 实测 available_memory=6.31 GiB、800 MiB 样本预算、5 个并行样本，继续检查实际结果。资源采样 logs/windows-x2648-resources.jsonl。
- WIN-LOG-01：源码启动器的 PowerShell 5 Tee 输出文件为 UTF-16；正常 stderr 首行会附上 NativeCommandError 的 PowerShell 包装文字，不能将此包装误判为应用失败。实际成功／失败仍按应用终态与产物判断。

- GUI-27（INPUT-11 TENCHISOZO DESIGN BU）：Host 6f11ff8 从一级目录一次加载六卷，各选 00001，2×6 共 12 集。全部章节边界、M2TS 与 EP01–EP12／卷号／命名已查看，版权裁剪体现在 split-parts 命令。63 行 SP 完整检查，27 行选中（7/4/4/4/4/4），其中六行分别附加 EP01/03/06/07/09/12；其余 21 个独立输出路径唯一。12 个短片与 24 个 IGS 不选，不重复一般 Remux。截图 screenshots/designbu-*.png。

- WIN-ENCODE-02：第一行在视频时间戳准备阶段失败，错误为 VK_ERROR_INCOMPATIBLE_DRIVER / Failed initializing vulkan device；默认 placebo 去色带无法初始化设备，无最终 MKV。后续行继续全源 getnative，已通过 GUI 取消，先检查 Windows 虚拟机 Vulkan 环境。失败报告保留在原输出目录；不按成功计。

- WIN-ENV-03：VirtIO GPU DOD 与 RDP 显示设备没有 Vulkan 驱动。下载 Mesa Windows 26.2.0 MSVC 构建并核对上游 SHA-256，仅为诊断解压至 C:\Software\Mesa3D-test-26.2.0；未改系统驱动注册表。用户会话通过 VK_DRIVER_FILES 可以加载 Lavapipe，现有 placebo 仍报告 Found no suitable device，环境限制暂记，未替换应用或滤镜算法。诊断日志 windows-placebo-user-smoke.log。
- WIN-ENCODE-03：19:19 经 GUI 将去色带调为 0；保留降噪 0.6、抗锯齿 0.5、裁剪／对比／FrameCheck 和 AAC 256。关闭本次重复 getnative，VPy 保留前次完整来源计算的 EP01=720p/bicubic_0.0_0.5、EP05=720p/lanczos2；原输出目录重新执行三行。首轮资源 612 次采样最低可用 4.098 GiB，观察到 5 个同时 VSPipe；取消等待当前样本批结束约四分钟，未启动后续编码且无最终文件。

- GUI-28（INPUT-12 Hanazakari）：Host 6f11ff8 一次加载 vol.01–04/BDROM，主 MPLS 分别 00008/00001/00008/00000，3＋3＋3＋3 共 12 集。全部章节、时长、EP01–EP12 和 Disc/卷号命名已查看；26 行 SP 全部检查，17 行选中（8/3/4/2），八个 IGS 与一条 17 秒短片不选。前三卷备用完整列表和四卷重复片段形成的 11:13:10 菜单仍默认选中，按既有 SP 策略记录观察，不执行冗余全盘 Remux。截图 screenshots/hanazakari-*.png。
- WIN-ENCODE-04：去色带为 0 后三行均完成 VPy 元数据初始化，但在 Video timestamp extraction 报 No video track found，批处理正确继续后续行，终态显示行错误，无最终 MKV。开始核对 Windows MKVToolNix 识别调用与返回；旧失败报告保留，重复失败使用唯一 .2 名称。

- WIN-PATH-FIX-01：Windows 真实诊断确认原始 Y: 路径存在、normcase 转为全小写后不存在。MKVToolNix 本身正常返回 video=0/audio=1，应用缓存辅助函数却因小写路径 stat 失败返回空结果。已保留访问路径大小写，修复同一边界的 MKV/MPLS/M2TS 缓存访问；20 项既有相关测试、mixin 契约、编译、UTF-8/CRLF/diff 通过。同步 Windows 170 文件逐个验证（仅 1 文件更新）；真实 MKV 识别、Z: 原盘 MPLS 四个 PlayItem 和 M2TS 解析、缓存复用均通过，见 reports/windows-path-case-{before,regression}.json。当前重启 GUI 准备同输出目录回归，尚未提交。

- COMMIT-16：9efb260 / fix(media): preserve path case on Windows shares，1 文件、2 行增加／1 行删除，已提交并推送 origin/main（6f11ff8→9efb260）。20 项相关既有测试、真实 Windows 共享盘三类读取及缓存复用、编译／mixin／UTF-8／CRLF／diff 通过。Docker 已重建（sha256:d97b38701ca212255eff9ec9ce0f23cbc201d68a6afa298b801ff7000d1d89d5）；恢复既有路径行为，无需增加 README 或历史。
- WIN-ENCODE-05：Windows GUI 9efb260 三行成功。x264 8-bit / AAC 256 kbps，EP01、EP05、OP 各 360 帧；全部 1,080 个 PTS 与来源逐帧相等。EP 为 1920×1080，OP 按 GUI 自动裁左 2 像素为 1918×1080；三段完整音频分别 1420.032/1420.032/90.026 秒，来源 1420.015/1420.015/90.010 秒，编码包时长差不超过 17 ms，实际 AAC 码率均约 256 kbps、48 kHz 双声道。完整音视频严格解码无错误，三份 FrameCheck 均 pass/360/0 suspect，最低 Y PSNR 43.84/44.06/43.79 dB。报告 reports/windows-x2648-aac256-validation.json。
- WIN-VALIDATE-01：独立 FFmpeg null 输出检查最初因其输出时间基推断产生两条 non-monotonic DTS，成品 360 帧实际 PTS 正确；改用 passthrough 并保留 demux 时间基后无错误。仅修正仓库外验证命令，未改变成品或应用，诊断 reports/windows-decode-validation-diagnostic.json。
- WIN-BUILD-01：已从与 9efb260 一致的同步源码启动新 PyInstaller 构建，独立目录 C:\src\BluraySubtitle-builds\20260909-9efb260，保留既有发布包；日志 logs/windows-build-9efb260.log，完成后继续打包版 GUI／工具／多进程验证。
- GUI-29（INPUT-10 Mai，进行中）：十卷已逐卷查看，结合原盘 SCANS 封套确认分组：1–3 为 HiME（12＋11＋3），4–5 为 Otome（13＋13），6/7 为 Otome 特典，8 为 Zwei（4 集），9 为总集篇，10 为 S.ifr（3 集）。已通过 GUI 部分勾选 1–3，26 行分集边界与命名全部查看；长于普通 TV 的行包含封套所列随集特典，并非按时长强行修正。继续各组 SP 与其余组分集检查。

- WIN-BUILD-02：PyInstaller 6.22.2 新包构建成功，约 255 秒，EXE SHA-256=3e2f84ff6c927167fd31a489e558965bc7131a30aca06549f1c3095a241b5400；构建前 C: 可用约 205 GiB、客体可用内存约 6.84 GiB。构建目录及报告 windows-build-9efb260.json 已保存，GUI 与冻结多进程尚待验证。
- GUI-30（Mai 的 HiME 组）：仅选第 1–3 卷，12＋11＋3=26 集，EP01–26、原始卷号与全部章节边界已查看。38 行 SP 全部检查，26 行选中（1/2/23），三条 1 秒版权片与九个 IGS 不选；第三卷 SP01–23 含封套列出的活动、PV、导演剪辑、声优访谈等，名称唯一。截图 maihime-episodes-*.png、maihime-sp-01/02.png；继续 Otome、OVA 与特典组。

- WIN-PACKAGE-01：9efb260 打包版经系统 Edge GUI 正常启动、最大化，Built-in VapourSynth／编码器可选，能从 Y: 加载完整 90 秒 OP 素材与独立 360 帧 VPy。导入 OP.ass 时发生 UnicodeEncodeError：冻结程序重定向标准输出仍为 GBK，连日志模板中的半角 Unicode 引号 U+FF62 都无法输出，字幕扫描因此失败；原始 traceback 保存于 logs/windows-app-bundle-9efb260.log。尚未实际启动该包的 SVT Encode，不计通过。
- WIN-STDIO-FIX-01：在 Windows 入口调用 freeze_support 前将可配置的 stdout/stderr 统一为 UTF-8/backslashreplace，兼顾冻结子进程及无控制台流。仓库外实际 GBK TextIOWrapper 启动诊断通过：中文、半角引号与 emoji 均完整输出，freeze_support 前编码已生效，无控制台入口也正常；编译、UTF-8/CRLF/diff 通过。正在同步并重建专用包作 GUI 回归，尚未提交。

- COMMIT-17：cd12f76 / fix(windows): use UTF-8 for redirected application logs，1 文件新增 5 行，已推送 origin/main（9efb260→cd12f76）。新 PyInstaller 包经 GUI 导入字幕不再出现 UnicodeEncodeError，关闭后日志完整保留 ｢…OP.ass｣；无控制台及 GBK 流的入口诊断、编译／UTF-8／CRLF／diff 通过。包位于 20260909-stdio-fix，EXE SHA-256=be08b7eefccff4ff92f84842060f2e5765103ff3ccf27ccd53773f2bd51f2a9a。
- WIN-GUI-FIX-01：成功扫描字幕后，Remux 来源 Encode 误走原盘 Encode 的结果分支，将现有视频行清空并改为 ENCODE_LABELS，造成列与 VPy 控件错位；实际压制未启动。截图 windows-remux-subtitle-columns-corrupted.png。已增加 Remux 输入结果处理：按当前视频行顺序只更新字幕路径，保留行数、来源身份、输出名及控件；字幕多于正片行时明确提示且不修改原行；输入模式切换后忽略旧扫描结果，Remux 行拖动／排序不再重建 MPLS 配置。英／中文 README 说明顺序映射，错误文本同步 i18n。当前待 GUI 回归，尚未提交。
- GUI-31（Mai 的 Otome／OVA）：只选 4–5，13＋13=26 集全部章节与命名查看完毕；10 行 SP，3 行选中（1/2）、两条短片和五个 IGS 不选。单独选择 8 后 Zwei 四集正确，7 行 SP 中三行选中、一短片三 IGS 不选；单独选择 10 后 S.ifr 三集正确，7 行 SP 中四行选中、一短片两 IGS 不选。截图 maiotome-*.png、mai-zwei-episodes-sp.png、mai-sifr-episodes-sp.png。仍需 6/7/9 特典电影分组收尾。

- GUI-32（INPUT-10 Mai 完成）：仅选 6/7/9 并切电影模式，三个完整主输出分别 00:07:57.477 / 00:50:41.038 / 01:44:53.954，原始卷号 006/007/009、全章节范围与唯一文件名正确。40 行 SP 全部查看，27 行选中（21/4/2），三条 1 秒片段、一条 23 秒片段和九个 IGS 不选；截图 mai-bonus-*.png。至此五个分组覆盖全部十卷：TV/OVA 59 集＋三个特典完整主输出，全部 102 行 SP / 63 个默认选择已核对，不进行重复普通 Remux。报告 reports/mai-complete-gui-validation.json。

- WIN-GUI-FIX-02：20260909-remux-subtitles-fix 打包版 GUI 导入一份 ASS 后，原始来源、90.010 秒时长、自定义输出名 OP-Frozen-SVT10.mkv 与独立 VPy 均保留；导入两份 ASS 对一行时提示数量 2/1，原配置保持。冻结字幕解析观察到三个应用进程，Unicode 日志正常。21:23 创建此前选择但尚不存在的空输出目录后，经 GUI 启动 SVT-AV1 10-bit／Opus Auto／硬字幕及完整来源 getnative。报告和资源继续采样。
- WIN-GUI-FIX-03：Host 两行实际 GUI 验证字幕导入和输出名称排序均保留各自字幕／VPy，但随后拖动暴露 CustomTableWidget 的 takeItem/removeRow 会丢失文本和嵌入控件。已改用 model.moveRows，并将 DiscTableWidget 的既有安全拖动流程共用到该表格；9 项既有原盘选择／Encode 测试、i18n、mixin、编译和 UTF-8／CRLF／diff 通过。正在做真实拖动回归，尚未提交。截图 remux-subtitles-drag-cleared-row-before-fix.png。

- COMMIT-18：7ed7949 / fix(gui): preserve Remux encode rows during subtitle operations，六文件修复及中英文说明已推送 origin/main（cd12f76→7ed7949）。真实 GUI 双行导入、按名称排序、双向拖动、移动后轨道编辑来源均通过；9 项既有相关测试及 i18n／mixin／编译／UTF-8／CRLF／diff 通过。报告 reports/remux-subtitle-row-preservation-regression.json。正在更新 Docker 与 Windows 打包版。
- WIN-ENCODE-06：打包版 SVT-AV1 10-bit／Opus Auto／硬字幕输出 OP-Frozen-SVT10.mkv。360 帧时间戳逐帧与来源一致，1918×1080、yuv420p10le；完整 48 kHz 双声道 Opus 90.017 秒（来源 90.010 秒），实际码率约 130.06 kbps，命令明确使用 128k VBR。完整音视频严格解码通过，FrameCheck pass／360／0 suspect，最低 Y=43.93 dB。第 5 秒和第 10 秒目视确认合成字幕 A/B 正确烧录；getnative 完整来源 6 个样本中 5 个有效、1 个纯色跳过，最终 720p/bilinear。报告 windows-frozen-svt10-opus-hardsub-validation.json。
- WIN-MP-01：冻结程序 getnative／Encode 阶段 297 个资源样本，最多 7 个应用进程、5 个 VSPipe（第 6 个纯色样本提前结束）；最低可用内存约 2.562 GiB、所测相关进程合计最高工作集约 4.169 GiB。没有冻结子进程启动错误；报告 windows-frozen-resources-summary.json。
- WIN-TOOL-OBS-01：成品生成后 Windows FFprobe 报 AV1 chroma_location 未知，GUI 明确以警告完成并保留文件和报告。同一文件在主机 FFprobe 为 left；Windows 系统／包内 FFprobe 的 stream、首帧、五帧探测均省略此字段。按工具差异暂记，未删除警告或修改成品。报告 windows-av1-chroma-probe.json。

- WIN-BUILD-03：7ed7949 同步到 C:\src 后 170 个文件散列全部核对，更新五个文件并保存备份。新包位于 C:\src\BluraySubtitle-builds\20260909-7ed7949，21:43 构建成功，EXE SHA-256=75f72751316303409781dbcc37d0dcc0f66c0aa0251dfb3be915478cd64ee935。Docker 同提交镜像已构建，ID=sha256:ce7ffab7a130ff3581155119d5de7438a9651f26ce92877f2984304e5b38f5d2。
- WIN-TOOL-02：包内 7-Zip 实际创建／解压 ASS，文件字节相等；Windows Python 入口调用 ass2sup，2 个并行进程完成两个字幕事件，SUP 标识有效。包内 mkvpropedit 在本轮成品副本中写入章节／视频语言／附件，mkvinfo、mkvmerge 识别及 mkvextract 章节／附件读回通过，附件字节相等；Windows hdr10plus_tool 对完整 259 帧上游样本提取的 SceneInfo 与参考 JSON 相等。报告 windows-tool-commands-7ed7949.json。
- WIN-TOOL-03：tsMuxer 直接 mux 到 WinFsp Y: 失败，读取 Y: 写入 C: 和全 C: 均成功。按应用实际参数进一步检查 demux 模式，Y: 输出成功，373 帧 HEVC 大小 56,336,759 字节，SHA-256=dfa556db0049c553b6bb91dc3bff1fbcc857cdea6fa6d070727799c488423084，与原 BL 完全相等。带 --no-asyncio 的对照也相等；应用当前使用的 demux 流程无需修改。只将 mux 模式共享盘限制作为外部工具观察。报告 windows-tsmuxer-{path,demux}-diagnostic.json，上游参数说明 https://github.com/justdan96/tsMuxer/blob/master/docs/USAGE.md。
- WIN-PREVIEW-01：GUI 的 Edit 按钮使用系统文件关联，未配置 .vpy 默认应用时 Windows 正常弹出选择应用；取消该提示，未改用户关联。Preview 能启动随包 VapourSynth Editor 并打开指定脚本，但执行预览两次退出。Windows Application Error 指向包内 vs_pkg/vapoursynth64/plugins/libvs_placebo.dll，0xc0000005；记录 windows-vsedit-preview-events.json，暂缓环境调查。测试脚本准备时曾误替换后面的 antialiasing_strength 计算，导致缩进错误，已在仓库外修正并编译检查；该准备错误不计应用缺陷。
- WIN-DV-01：最新打包版 GUI 导入两份内挂 ASS，并拖动为 Zootopia→Minecraft；字幕、名称、时长与独立 VPy 完整保留。21:59 启动 x265 Main10、ultrafast/CRF24、完整 360/373 帧、裁剪／对比／FrameCheck。Windows 编码器走编码后 dovi_tool 注入 RPU 的回退流程，4K 来源 getnative 按规则跳过。两行均完成，终态只提示未利用 FEL 残差。默认保留 Atmos TrueHD；不能将这轮记为 FLAC 转换通过。独立媒体／RPU 验证继续，截图 windows-dv-rows-after-drag.png、windows-dv-completed.png。

- WIN-DV-02：两份 Windows x265 成品独立验证通过，共 733 帧显示时间戳逐帧一致；Zootopia 为 3840×1608，Minecraft 为 3840×2160，均 Main10、P8.1、EL=0。全部静态色彩／HDR 字段一致，完整 TrueHD PCM s32le 散列与来源一致；每份两条新增 ASS 事件的时间和文本精确相等。Windows 注入流程生成的全部 RPU JSON 与此前已逐帧核对来源的 Linux 输出完全相等，含 Zootopia 全 360 帧 L5 上下 276→0。两份 FrameCheck 均 0 suspect，最低 Y=48.58/48.08 dB，完整音视频严格解码无错误。报告 windows-x26510-dv-softsub-validation.json、reports/windows-dovi-output/。

- WIN-MERGE-01：7ed7949 打包版 GUI 使用五卷完整 MPLS 元数据副本、16 份真实 ReZero CHS ASS。全部行的原盘序号、章节和偏移已查看，自定义 .zh-Hans 后缀；完成五卷合并和完整原盘目录选项。5 对输出字节分别相等；与此前已独立验证的 Host 输出比较，统一换行后全部文本、样式与 8,680 条事件（8,058 条 Dialogue＋622 条 Comment）完全相等。179 次资源采样最多 13 个冻结进程，最低可用约 6.679 GiB。再次点击执行明确拦截已有输出，10 个文件大小与 mtime 均不变。报告 windows-frozen-merge-rezero-validation.json、windows-merge-output-conflict.json。
- WIN-FLAC-01：包内 ffmpeg 提取完整 90 秒 OP 音频为 PCM24 WAV；包内 flac.exe 用 --best --verify 编码并解码，所有命令 exit 0。往返 PCM s32le SHA-256 均为 6614a3c3a57599578fe1a7e4dd27672cbc217c371cfce735fd94cf2938a16e17，报告 windows-flac-roundtrip.json。
- WIN-CHAPTER-01：章节短样本的原始 MPLS 只有 0 秒起始标记，按现有 MKV.add_chapter 规则跳过无导航意义的单起始章节；未认定为应用缺陷。使用 src/bdmv/MPLS.save 只在本轮元数据副本中增添 5 秒标记，原副本备份到 state/windows-chapter-fixture-original.mpls，用户原盘没有改动。GUI 重新加载后以“直接编辑原文件”处理本轮 MKV 副本，正确增加 Chapter 01/02，时间 0/5 秒；全部 19,045 个音视频／字幕包的 PTS/DTS、时长、大小和 SHA-256 与输入相同。报告 windows-chapters-validation.json。

- WIN-HDR10PLUS-01：7ed7949 打包版 GUI 以 x265 12-bit、ultrafast/CRF24 和原生 --dhdr10-info 完成完整 259 帧上游测试样本。独立检查 yuv420p12le、全部 PTS 和 259 个 SceneInfo 与来源/上游参考精确相等，完整解码无错误，FrameCheck pass/0 suspect（最低 Y=62.70 dB）。这是 256×144 全黑元数据样本，未作为真实 4K 画质通过。报告 windows-main12-hdr10plus-validation.json。

- GUI-33（INPUT-24 Bucchigiri）：Host 7ed7949 从一级目录加载四卷，各选 00001，3×4=12 集；全部章节、M2TS、EP01–12 和卷号／输出名已查看。54 行 SP 全部核对，33 行选中（8/6/7/12），其中九行附加 EP01/02/04/06/08/09/10/11/12；其余 24 个独立输出为 20 个 SP＋四个菜单，与 jsum U2 #64117 文件表吻合。八个 13/15 秒短标志与 13 个 IGS 不选；四个 10:48 循环菜单按当前策略保留，未改算法或重复普通 Remux。来源 U2 #64106 hash 与任务匹配。报告 bucchigiri-gui-validation.json、u2-bucchigiri-jsum-reference.json，截图 bucchigiri-*.png。

- GUI-34（INPUT-26 ODDTAXI）：Host 7ed7949 一次加载两卷。默认 00000 把约 24 分钟正片与广播剧 PlayItem 交替串联，部分默认分集包含广播剧；对照 wiki 的多主 MPLS 操作，通过 GUI 改选第一卷 00003–00009、第二卷 00003–00008，得到 7＋6=13 集纯正片，全部 chapter 01→ending、M2TS 和 EP1–13／卷号／文件名已核对。17 行 SP 全部查看，8 行默认选中（2/6），三条短片与六个 IGS 不选。已保存的 jsum #47597 文件表有 13 段广播剧等 SP；当前两个总 MPLS 作为 SP 整体保留正片＋广播剧，未逐段拆开，两个循环菜单也整体输出。该跨多集 SP 策略已记录为观察项，不进行重复完整 Remux。报告 oddtaxi-gui-validation.json，截图 oddtaxi-*.png。

- GUI-35（INPUT-28 Witch Craft Works）：Host 7ed7949 一次加载三碟，默认主 MPLS 00001/00001/00002；前两碟为 12 集，第三碟默认主内容为六段短动画合集，24:01 的独立内容保留为 SP。39 行 SP 全部查看，27 行选中（1/1/25），7 个 IGS、4 个短列表及完全覆盖的首段短动画不选。聚合列表与独立列表相差 2.002 秒的规则和 jsum 旧六卷版 #18315 对照已记录，未认定重复 SP 为新缺陷。GUI 取消第三碟后得到独立的十二集分组；EP05/EP11 自动结束章节 32 含下一集 35.035/35.994 秒，手动改为 31，相邻起始章节同步更新，全部章节与 EP01–12/卷号/输出名核对。记录自动估算需调整，不扩大修改；没有重复普通 Remux。报告 witch-craft-works-gui-validation.json，截图 witch-*.png。

- GUI-36（INPUT-27 Sonny Boy）：Host 7ed7949 一次加载 SONNY_BOY_1/2/BONUS，默认主 00000/00000/00035。正片 6＋6=12 集，各卷章节 01→04→07→10→13→16→ending，全部 M2TS 和 EP01–12/卷号/文件名已核对。BONUS 约 49 分钟制作花絮原按 24 分钟拆分，GUI 将结束章节设为 ending 后为完整 48:52.805 一行，并改名 Bonus - Sonny Boy Behind The Scenes.mkv。28 行 SP 全部检查，16 行选中（2/2/12），EP06/12 评论音轨准确关联；10 IGS 和两个短列表不选，四个静态内容行对应 PNG 或目录。与 jsum #46030 的 12 集和八类花絮/PV 内容对应，未重复普通 Remux。报告 sonny-boy-gui-validation.json，截图 sonny-*.png。

- GUI-NAME-01：Sonny Boy 的制作花絮行手动命名后，换成大和号一级来源，第 13 行继承了上一部的名称。已保存 yamato-stale-custom-name-before-fix.png；根因是新来源仍复用旧 table2 行，on_configuration 按同一行号保留手动名称。候选修复在原盘来源真正改变时清空该来源的输出行及派生配置；同来源更新、字幕合并/添加章节的独立输入表保留原流程。9 项既有相关测试、mixin 契约、编译/UTF-8/CRLF/diff 检查通过，GUI 重现验证进行中，尚未提交。

- GUI-NAME-02：修复版本 GUI 再次加载 Sonny Boy，先把第 13 行命名为 Source A custom bonus.mkv，再设结束章节为 ending；名称在同来源章节调整后保留。切换大和号并设 25 分钟后，第 13 行为正确的 EP13 宇宙戦艦ヤマト Disc3_BD_Vol_003-003.mkv，不再继承旧名称。报告 source-output-reset-regression.json，前后截图 source-name-*.png。
- COMMIT-19：6b651c5 / fix(gui): reset output rows when changing Blu-ray source，1 文件 6 行，已提交并推送 origin/main（7ed7949→6b651c5）。9 项相关既有测试、实际 GUI 来源切换及同来源名称保留、mixin 契约、编译/UTF-8/CRLF/diff 检查通过；恢复已描述的输出命名行为，没有增加文档或普通修复历史条目。Docker 和 Windows 最新构建仍为 7ed7949；最终平台收尾时需要更新到最新源码并做相关 GUI 回归，无需重复已完成编码矩阵。
- GUI-37（INPUT-07 大和号）：Host 6b651c5 一次加载 YAMATO_TV_DISC1–5，全部主 00001。每集估算设为 25 分钟，得到 5＋5＋6＋5＋5=26 集；全部起止章节、M2TS、卷号和 EP01–26 名称已查看，跨来源名称问题修复后再次确认第 13 行。42 行 SP 全部检查，17 行选中（5/2/3/2/5），20 IGS 和五条短列表不选。五卷整条替代播放列表作为独立 SP；jsum #10775 旧版单独输出原版片头并多一张特典碟，按版本和整条 SP 规则记录差异，不将缺少该实体碟的内容认定为应用遗漏。报告 yamato-gui-validation.json，截图 yamato-*.png。

- GUI-38（INPUT-21 Avatar The Way of Water）：Host 6b651c5 电影模式一次加载一级原盘，默认仅 00800，正片 03:12:34.167、chapter 01→ending，电影标题输出名已查看。95 行 SP 全部核对：17 个 MPLS 输出（含 8 个 PNG）＋00085/00116 两个无 MPLS 视频，共 19 个；两个已覆盖整片列表不选，其余短内容按既有规则处理，三个以上片段的短列表保留。00020 约 159 分钟的独立列表按整体 SP 规则记录观察。报告 avatar2-gui-validation.json，截图 avatar2-sp01–08.png、avatar2-main*.png。
- GAP-PREP-01：只读核对水之道 75 个 MPLS 和 123 个涉及文件的 PAT/PMT，本份输入未发现“STN 已声明但 PMT 缺失”的选轨片段。00150 是 41.375 秒影音片段＋0.250 秒纯视频尾段，尾段 STN 没有声明音轨，属于原生合法空档。报告 avatar2-playlist-physical-gaps.json。已准备原 MPLS 字节副本，以及按授权编辑的四 PlayItem 测试副本（纯视频→影音→纯视频→影音，在全部段声明同一 AC3 槽位），后者用于检验开头/中间物理缺轨开关。两份都链接原始媒体字节，原 MPLS SHA-256 核对未变；报告 avatar2-gap-fixtures.json。

- GAP-01：原生 00150 副本在部分缺失选项关闭时成功 Remux，998 个视频包全部 PTS、995 个可用 DTS 误差小于 0.801 毫秒；1,293 个 AC3 帧编码负载散列完全相等、PTS/DTS 精确对应。HEVC VCL 在排除每段最后 NAL 后的 6 字节 Annex-B 零填充后全部相同，严格完整音视频解码无错误。报告 avatar2-native-media-validation.json、avatar2-native-vcl-diagnostic.json。独立验证器先处理 FFprobe 不提供部分首帧 DTS、以及 Annex-B 尾部填充的差异；未据此修改应用。
- GAP-02：四段“已声明但物理缺失”副本关闭策略时明确报 00000.m2ts 缺少 audio PID 0x1100，输出目录无任何媒体文件，报告 avatar2-declared-gaps-off-validation.json。开启后已从 GUI 成功执行，产物位于 ${OUTPUT_ROOT}/Remux/avatar2-declared-gaps/Disc.mkv；保存设置重新应用了默认输出目录，实际路径已记录，没有重复执行来改变路径。开关已恢复测试前 true。逐包验证发现最大约 1.345 毫秒视频时间量化差异，正在分段核对而未直接放宽判定。

- GAP-03：开启部分缺失后成品独立验证通过，1,996 个视频包/VCL 与源片段顺序一致（规范化 Annex-B 尾部零填充），2,586 个 AC3 帧编码负载完全相等。音频起点 0.250 秒，中间空档为 41.626–41.876 秒，无填充音频帧；严格完整音视频解码无错误。逐段核对确认视频分段原点误差≤0.845 毫秒、段内 PTS 量化误差≤0.501 毫秒，整体最大 1.345 毫秒；音频每段内时间差精确一致，原点误差≤0.845 毫秒。Matroska Block 保存 PTS（[规范说明](https://www.matroska.org/technical/notes.html#block-timestamps)），FFprobe 的视频 DTS 保留为诊断数据，以呈现时间线、完整 NAL 顺序和严格解码判断成品。报告 avatar2-declared-gaps-media-validation.json、avatar2-declared-timestamp-quantization.json；媒体仍在 ${OUTPUT_ROOT}/Remux/avatar2-declared-gaps/Disc.mkv。
- MENU-REVIEW-01：已核对 media_info_and_track_mapping.py:_detect_sp_looping_mpls 的 all_same/two_clip/tail_repeat 三分支，分别保留一或两个 PlayItem；SP 执行阶段将 max_clips 和 split_parts 应用到直接和回退路径。此前只根据 GUI 的总时长推断菜单会产生冗长成品并不充分，相关观察改为待实际输出验证。

- GUI-39（ODDTAXI 用户指定方式复查）：两碟继续选 00000，通过“查看章节”取消广播剧区间：第一碟 Chapter 6/12/18/24/30/35/41，第二碟 5/11/17/22/28/31。应用后正片仍 7＋6=13 集、EP01–13，所有 M2TS 与起止章节正确排除广播剧，完整切分命令同步更新。41 行 SP 全部核对，19 行选中（8/11），其中 13 行正好是单独的广播剧章节 SP，其余六行包含菜单与其他特典；各集替代 MPLS 被覆盖且不选，不再把整条总 MPLS 作为 SP。报告 oddtaxi-chapter-gui-validation.json，截图 oddtaxi-chapter-*.png。此为当前采用的操作；早先单集主 MPLS 的替代测试不作为推荐流程。

- GUI-40（Sonny Boy 用户指定方式复查）：保持 BONUS 原盘勾选，只取消其 00035 主 MPLS。正片表立即只剩 12 集 EP01–12；完整 48:52.805 花絮进入 SPs/BD_Vol_003_SP06.mkv，不需要手动调章节或改名。29 行 SP 全部查看，17 行选中（2/2/13），EP06/12 附加评论音轨保持正确，四个静态内容行和十个不选的 IGS 保留。报告 sonny-boy-no-main-gui-validation.json，截图 sonny-no-main-*.png。

- W64-01（用户补充）：取紫罗兰第二卷 theater ver 的完整主 M2TS 00000、PCM PID 0x1101，48 kHz/5.1(side)/24-bit，进行实际外部 FFmpeg 命令测试。76.8 秒提取完成，W64 大小 4,798,267,328 字节（4.468735 GiB），data 部分 4,798,267,200 字节，266,570,400 个采样帧、时长 5,553.55 秒。RIFF/data 64 位长度均正确，FFprobe 可完整读取；W64 全部 PCM 数据 SHA-256 与同时从来源计算的 PCM hash 完全一致（2ad27608558ca381571be92109a562242a26c607b93d291e214db0b446c88379）。原源文件大小/mtime 未变。报告 violet-theater-w64-validation.json，文件 Fixtures/violet-theater-w64/theater2-5.1-24bit.w64。此项为外部工具大于 4 GiB 实测，不重复整卷 Remux/Encode。

- MENU-01：从 GUI 执行三个仅 SP 的菜单回归：芙莉莲第三卷原始 all_same（51 段）、Bucchigiri 原始 tail_repeat（12 段），以及用同一真实 A/B 片段构造的交替 two_clip 测试副本（12 段）。三个成品分别 72.281、108.108、108.108 秒；全部视频 VCL 及顺序与预期一/两段相同，1,733/2,592/2,592 帧，最大 PTS 量化误差 0.501 毫秒以内，严格完整音视频解码无错误。all_same 全部 PCM 精确一致；双片段成品 PCM 与完整 A+B 来源串联后的同长度前缀完全相同，最终少 96 个采样帧（2 毫秒，均为零值），由各来源音频最后一个包越过 PlayItem 1 毫秒以及最终边界裁切产生；不等于逐 PlayItem 各裁 48 个采样，保留此量化观察。未发现菜单循环未缩短问题。所有原始 MPLS SHA-256 未变。报告 menu-loop-fixtures.json、menu-loops-media-validation.json，GUI 截图 menu-loops-*。

- GUI-41（INPUT-14 默示录的四骑士）：完整一级目录含 12 张盘，9 张正片盘主 MPLS 均为 00001，每碟 4 集共 36 集；三张特典盘保持勾选，仅取消 00002/00009/00003 主 MPLS。最终 EP01–36 全部章节、M2TS、卷序和文件名核对通过。91 行 SP 全部检查，选中 30 行（正片盘各 1，三张特典盘 2/11/8），21 个 IGS、40 个短 MPLS 不选。完整 56:54.678 特典成为 BD_Vol_010_SP02.mkv。既有 U2 #64491 候选列表为空，无可直接对照的 jsum 版本。本项无额外普通 Remux，报告 nanatsu-gui-validation.json、截图 nanatsu-*。

- GUI-42（INPUT-17 变形金刚）：三碟完整一级输入，默认主 MPLS 均 00001。将估算单集时长 24 改为 23 分钟后，35＋30＋33=98 集，常规集按每 5 章节切分。最后三集偏短，再将 EP96/97 结束章节 157/162 改为 156/161，最终 151→156→161→ending，时长 21:47.306/21:16.775/21:26.285。所有 98 行正片的卷序、M2TS、章节、文件名均查看；21 行 SP 全部核对，选中 12 行（3/5/4），3 个 1 秒短片与 6 个 IGS 不选。U2 #64203 发布页菜单图明确有“全篇播放／仅本篇播放”，各盘 00002 跨多集省略片段，按已记录的部分匹配规则作为普通 SP，不能把其较长时长归为菜单循环问题。独立封面附加命令路径正确。没有重复完整 Remux。报告 transformers-gui-validation.json、截图 transformers-*。

- SCOPE-03（用户补充）：已读取 9 月 3 日两节重构历史，并对照本轮 1c7eee0→6b651c5 改动。src/runtime/audio_conversion.py、src/bdmv 与核心逐 PlayItem 缺失/空档路径未修改；三张 UHD 的完整缺失轨道回归、额外 FLAC/AAC/Opus 空档组合和既有负向分支重复测试取消。用户补充前已完成的 GAP-01–03 结果保留。与本轮 SP 调用和 Windows 路径处理有关的测试已有各自证据，不重复整盘。报告 previous-sparse-track-coverage-audit.json。
- MYGO-01（新增检查进行中）：用户提供 jsum #63009。已通过 Edge 阅读，发布者明确指出直接转换的布局问题；官方前后篇产品页均标明 PCM 3.1。现有两个原始 M2TS 的 PID 0x1101 经 FFprobe 均显示 48 kHz/24-bit/4 声道/4.0，异常已在 FLAC 转换前出现。开始从 GUI 仅选前篇完整 PID 0x1101，验证当前程序实际输出；不得仅因声道数为四就判定 3.1 正确。

- MYGO-02：GUI 完整前篇音轨转换完成，成品为 48 kHz/24-bit FLAC，仍标为 4.0（FL/FR/FC/BC），不能认定自动处理成正确 3.1。完整 340,852,560 个采样帧、7,101.095 秒、4,090,230,720 字节 PCM 与原始 PID 0x1101 的整体 SHA-256 及四个声道各自 SHA-256 全部相同，没有掉样或重排。MKA 另保留一条英文 PGS（实际选轨结果已记录），不影响音轨检查。第四声道全轨有 42,432,618 个非零样本；6500 秒处样本 99.918% 能量低于 150 Hz，与 LFE 用途相符。
- MYGO-03：外部工具验证可在任务副本上仅改 FLAC 的 WAVEFORMATEXTENSIBLE_CHANNEL_MASK，从 0x0107 改为 0x000F；编码帧 SHA-256 完全不变，不需要重编码或增加左右后方空声道。完整修正 FLAC 和重新混流的 MKA 均显示四声道 3.1/48 kHz/24-bit。文件 Fixtures/mygo-channel-mask/MyGO-Part1-3.1.flac、.mka；报告 mygo-audio-layout-validation.json、mygo-channel-mask-external-validation.json。当前程序保持由来源解码器提供的 4.0 标识，不会依据作品名称推断 LFE；未为所有四声道新增错误的自动转换规则。按已授权的暂缓原则，将这种来源布局歧义记录为需手动明确布局的兼容观察。官方来源：https://mygo-movie.bang-dream.com/blu-ray/；FLAC 掩码规范：https://www.rfc-editor.org/rfc/rfc9639.html#section-8.6.2 。
- REF-UPDATE-01：用户补充的 jsum #63009 已读取并保存清单，包含前后篇两个 MKV 和每卷两个菜单 PNG。此前“未找到 jsum”仅是初轮检索结果，现以此引用更新 INPUT-08；不再使用仅覆盖前篇的 #63017 作为主要参照。

- GUI-43（INPUT-20 Avatar 2009）：75 个 MPLS，电影模式仅默认主 00800，39 个 PlayItem，共 02:42:02.003，chapter01→ending、Avatar.mkv。93 行 SP 全部检查，选中 22（17 个 MPLS：8 PNG＋9 视频；5 个独立 M2TS：00074/00076/00083/00101/00105）。00004/00801 与主条目顺序及时间范围完全一致，覆盖不选；55 个短 MPLS 和14个短独立片段不选。大于等于3段的短MPLS例外保持现有规则；0020长菜单不误判为成品冗长。按SCOPE-03不重复整盘缺轨测试。报告 avatar2009-gui-validation.json、截图 avatar2009-*。

- COMMIT-20：8f98d36 / fix(gui): synchronize initial movie output commands，已推送 origin/main（6b651c5→8f98d36）。工作区干净。首次加载电影时，在选轨与输出表完成后再同步混流命令，消除 MyGO 两卷命令错误使用同一个目录名；已有明确电影输出名称时不再重复追加版本号，消除 Black Hawk Down 的 _1_1/_2_2。9 项现有相关 unittest、split 契约、编译、UTF-8/CRLF、diff 检查及两种真实输入 GUI 回归通过。只改一份源码（3增1删），无新增测试、普通修复历史或 README。当前 日志 host-app-movie-command-sync-v2.log。报告 movie-initial-command-regression.json；最终 Windows/Docker 构建须包含此提交。

- GUI-44（INPUT-23 Black Hawk Down收尾）：8f98d36 首次加载自动选00501/00503，分别37个PlayItem、02:24:18.649/02:31:50.601；输出_1/_2且与命令一致，chapter01→ending。174个MPLS，172行SP全部查看，5行默认选中（00001/00080/00099/00102视频，00104PNG）；110个短片不选，55个正片片段00401–00455及两个完整替代00502/00504被主版本覆盖不选。独立核对00501=00502、00503=00504的全部时间范围和片段顺序。00099为100次单片段循环，由MENU-01所核对的既有逻辑缩短。未增加普通完整Remux。报告blackhawk-gui-validation.json。

- GUI-45（INPUT-29 Zootopia 2）：一级目录及其解压原盘，电影模式仅选00800，01:47:44.833、chapter01→ending、Zootopia 2 - Ultra HD™.mkv；命令与输出表一致。250行SP全部查看，32个选中且SP01–32无重名；00801/00803/00804/01309完整替代不选。01476/01478虽只有20.020/22.022秒，按三片段以上例外保留；01627双片段循环菜单的原列表时长不作为成品时长。完整短DV、RPU裁剪及跨平台媒体结果沿用已有验证，不额外执行完整电影。报告zootopia-gui-validation.json。

- GUI-46（INPUT-03 Re:Zero S3收尾）：五卷均主00001，第一行结束章节改ending后1＋4＋3＋4＋4共16集，所有章节/M2TS/命名再次核对。65行SP全览，49行选中（7/11/10/11/10），八条分集附加分别对应EP02/03/07/08/09/11/14/16；15个IGS和第一卷已整条附加的00002不选。既有90分钟双FLAC和所有ASS/SUP验证保留。报告rezero-final-gui-validation.json。

- GUI-47（INPUT-18 四月收尾）：9卷主00001，1＋2＋2＋2＋3＋3＋3＋3＋3共22集；全部正片章节、M2TS和命名正确。42行SP全览，选中22（4/2/2/2/2/4/2/2/2），20个IGS不选，无名称冲突。既有22集大ASS全量验证保留，不重复普通Remux。报告shigatsu-final-gui-validation.json。
- DOCKER-BUILD-10：8f98d36最新镜像构建成功，sha256:2d61a4198029046d5ab2ada861c643361062606e68930a41b9bae774859339bd；待最终GUI回归。

- GUI-48（INPUT-22 bd-saw收尾）：原始字母序4卷的22行SP全部查看，默认14行选中（4/3/2/5）、四个短MPLS和四个IGS不选。DISC1/00002是可见的普通菜单视频，旧实测按需求手工取消后13个SP；不是循环未缩短问题。既有拖动顺序、部分勾选、全部13集和13＋13实际媒体/91个解码点验证保留，不重复输出。报告bdsaw-final-gui-validation.json。

- ISO-ENV-01：Fullmetal首次加载因默认/usr/local/bin/7zz不存在而明确失败，无字幕输出。设置的“检查工具路径”准确显示缺项；从本轮最新Docker镜像提取官方7-Zip26.03，安装到标准路径后GUI成功只读提取11个ISO的MPLS，未改仓库工具配置、未解压媒体。报告host-7zip-environment.json。
- GUI-ORDER-01（进行中）：真实Fullmetal混合输入最初将5个目录排在11个ISO之前；路径列旧比较器只比较basename，使BDROM仍在前面，字幕01错误映射到第12卷。已将原盘行改按完整可见路径比较，并让首次发现的来源按真实路径排列、保留用户既有顺序。9项相关现有unittest、split契约、编译和UTF-8/CRLF/diff通过；新默认已经01/02在前，继续验证正反排序和最终64集映射，尚未提交。

- GUI-ORDER-02：修复后默认源顺序01–16正确，路径列倒序16→1和正序1→16均通过；64行字幕的卷号、章节和偏移逐页核对与独立原始MPLS窗口一致。首次执行预检查提示第22行没有对应已选原盘，无输出，正在经GUI刷新确认；不能将可见映射检查当作实际合并成功。

- FMA-MERGE-01：刷新勾选恢复完整映射后，GUI全量合并64集成功。11个ISO各一个邻接ASS，5个目录各邻接及MPLS目录配对ASS，共21个.zh-Hans.ass；23,436条事件的文字、字段、样式全部与对应来源相同，最大时间量化差0.009156秒，五对输出字节一致。162个原ISO/M2TS/MPLS的size/mtime及MPLS散列未变。报告fullmetal-ass-merge-validation.json、fullmetal-original-source-guard.json。无重复输出或全盘视频解压。
- SUB-SELECT-01：取消第53行时，长单M2TS的分章循环读取已用尽的字幕时长列表，日志明确IndexError；恢复64行即成功。已补选中字幕耗尽的循环终止条件，14项现有配置/合并/选盘测试通过，正在GUI验证63→64行勾选，无需重写已有媒体。
- 用户补充（2026-09-10）：字幕合并及MKV添加章节界面隐藏无用混流命令列。已在表头展示边界按功能隐藏此列并保留Remux/Encode显示，尚待新GUI验证。当前日志host-app-subtitle-selection-final.log，三个小修复尚未提交。

- COMMIT-21：25a94b2 / fix(gui): correct disc ordering and subtitle input controls，3文件9增2删，已推送origin/main，工作区干净。混合来源按完整路径排序；字幕耗尽时停止分章匹配；按用户要求隐藏字幕合并和添加章节的混流命令列，并在Remux/Encode恢复。14项既有相关测试、split契约、编译/UTF-8/CRLF/diff通过。GUI确认63行重新匹配、未选第53行清空，再勾选后完整64行恢复；四种界面的列状态正确。无新测试或普通修复历史，最终展示wiki将采用新界面截图。报告subtitle-input-controls-regression.json。
- INPUT-COMPLETE-01：30个一级输入均完成各自授权范围（前29项GUI/分集/SP/命名，Fullmetal仅字幕合并）。芙莉莲第三卷双提供者实际媒体验证和最终平台/文档收尾仍未完成，整体目标继续。

- DOCKER-BUILD-11：25a94b2镜像构建成功，sha256:6b5ecdd2a78b70fb5899fdb90693db3cb2cbdf5cff41e412b6962eb669f85887；最终GUI回归待执行。

- REMUX-PROGRESS-01（用户补充）：确认章节早已完成，旧提示停留在给正片依次追加 SP 评论轨的两次整文件写入期间；随后最终 MKV 混流仍显示 FLAC 转换。将 SP 提示移到每项开始时，并区分准备、轨道追加、图片导出、轨道提取、转换及元数据；Remux 接入既有逐阶段音轨回调。补全目录的终端提示也从“清理临时文件”改为实际的蓝光目录补全。
- COMMIT-22：42cf069 / fix(remux): report the current processing operation，已推送 origin/main，3 文件 56 增 36 删。24 项已有相关测试及 i18n、split 契约、编译、UTF-8/CRLF/diff 通过。派生的短片段 GUI 完成两集、两条附加评论提供者、三段普通 SP，另一个仅导出请求完成 PNG 与裸 FLAC；截图捕获了准确的图片导出提示。原始音视频执行算法未改，没有新增测试、普通修复历史或 README。报告 remux-progress-regression.json、remux-progress-outputs.json。
- FRIEREN-REMUX-01：完整第三卷 GUI 已正常完成三集，EP1 含主音轨及两条评论轨（4353/4354），后两集各一条主音轨。两条完整评论轨 PCM 与源逐字节一致；主音轨为来源同长度前缀，片尾小量样本按 MPLS 窗口截取，完整视频/时间线/章节检查继续。独立验证脚本 state/validate-frieren-media.py 以流式哈希避免整集视频驻留内存。

- ENCODE-X2658-01：42cf069 宿主机 GUI 完成 OP 的 x265 8-bit 快速预设（fast / CRF20）补测，Main / yuv420p / 1920×1080，360 帧显示时间戳与来源完全一致。完整 90.01 秒音轨 PCM s32le 共 34,563,840 字节，与源散列相同；FrameCheck pass/360 帧/0 suspect，Y/U/V 最低 43.35/47.40/48.61 dB。已目视源与成品第180帧对比图。复用已经过完整 getnative 的 VPy，此次关闭重复 getnative 和自动裁边，保留图像处理及对比图。报告 x2658-flac-media-validation.json；验证按显示顺序比较 PTS，源 AVC 与成品 HEVC 的 B 帧包顺序不同不表示时间线变化。
- DOCKER-BUILD-12：42cf069 最新镜像构建完成，sha256:260d0ed6cf6f2c1a000560ffd4c4f85051e388708e20caf55ff6d85841a8c582。容器 bluray-subtitle-gui-test-20260909-42cf069 已从 GUI 启动，正进行最终 GUI 回归。

- FRIEREN-REMUX-02：三集全部独立验证通过，共 105,571 个视频包，完整 VCL 内容与顺序一致，最大 PTS 量化误差 0.5 毫秒；17 个章节与来源边界一致（误差≤0.4223 毫秒）。EP1 三条、EP2/3 各一条日语 FLAC，PGS 和封面保留；两条评论轨全轨 PCM 完全一致。三条主音轨分别仅裁去来源末尾 24/100/95 个全零采样帧，成品 PCM 与完整来源同长度前缀精确相同，对应 MPLS OUT 边界约 0.5–2.083 毫秒。三个成品完整音视频严格解码无错误。报告 frieren-dual-commentary-media-validation.json。独立验证首次在第三集收到终止信号（退出143），从检查点接续后完成，未重做前两集或修改媒体。

- WIN-FINAL-BUILD-01：更新结束后，运行已配置的 Mount Win11 Shared Folders 任务恢复 Z:/Y:。最新源码同步6文件、保留164文件，170个文件SHA-256全部验证。42cf069 PyInstaller构建成功，成品 C:\src\BluraySubtitle-builds\20260910-42cf069\dist\BluraySubtitle_windows_x64\BluraySubtitle_windows_x64.exe，SHA-256 4FDDADF842087C4829A9EFE7706D3F8EACD1684117660FA700F4132AB67E5B24。初次guest-exec响应超时但构建实际已开始，以实际日志和成功报告确认完成，没有重复构建。RDP最终GUI回归仍待完成。

- WIN-FINAL-GUI-02：42cf069 打包版通过 Edge/RDP 完成真实 GUI 回归：混合 ISO/目录初始 01→16、路径倒序 16→01 及恢复正序正确；64 集字幕取消第53行后该行映射清空、其余63行重新匹配，恢复勾选后完整64行映射复原，无 IndexError。Merge/Add Chapters 隐藏命令列，Remux/Encode 正常显示。没有重复合并或写入已有媒体。报告 windows-final-gui-regression.json；最新进度提示的实际媒体回归沿用 Linux REMUX-PROGRESS-01，不声明本次另做 Windows 完整 Remux。

- COMMIT-23：9afd36d / docs: refresh localized interface examples，已推送 origin/main。两份界面 wiki 各18幅对应语言截图；补充双电影版本、目录/ISO混合输入、ODDTAXI广播剧排除、Sonny Boy无主列表特典盘、芙莉莲双评论轨。保留 Hana/DaiNana 示例及引用锚点，明确 Hana需同时勾选两个主MPLS后排除NC重复章节，并删除固定旧行号引用。36张实际截图按原生JPEG格式发布，全部HTTPS返回200/image/jpeg且字节散列相等；本地链接/锚点、UTF-8/CRLF/diff检查通过。最初PNG扩展名检查发现浏览器实际返回JPEG，发布前仅更正扩展名，没有重编码图片。报告 wiki-screenshot-publication.json。
- AUDIT-SUPPLEMENT：最终功能覆盖审计补充高级用户预设管理与实际VFR/非零视频起点样本。已有CFR 360帧对比不自动等于VFR通过；派生360帧视频时间间隔41/42/83毫秒，首PTS375毫秒、末PTS20212毫秒，保留完整90.01秒FLAC。准备检查GUI保存/重命名/应用/删除用户预设、直接参数覆盖与实际编码时间线。报告 vfr-offset-fixture.json，未重复原盘Remux或getnative。

- PRESET-GUI-01：Docker 42cf069 经 GUI 验证内置名称只读/删除禁用；新增 New Preset 后改名 Codex VFR temp、编辑为 --preset ultrafast --crf 22，保存后在 Encode 页能选择并正确填入。直接把参数改为 CRF21 后，预设名保持，成品 x264 SEI 确认 crf=21.0；重新打开设置仍是原预设 CRF22。经 GUI 删除临时预设，恢复 x265/10-bit/Balanced；JSON结构与补测前完全相等。报告 custom-preset-gui-validation.json。
- VFR-ENCODE-01：Docker GUI 完成 x264 8-bit／VFR／硬字幕／五种图像处理。360个视频PTS与来源精确相等，首点375毫秒、末点20212毫秒、间隔41/42/83毫秒；降噪0.6、去光晕0.2、去振铃0.2、去色带0.5、抗锯齿0.5实际执行。FrameCheck pass/360/0 suspect，最低Y=39.70 dB；完整音视频严格解码通过。目视frame4无字幕、frame8在0.790秒出现VFR A、frame16无字幕、frame180在10.335秒出现VFR B，符合两段ASS时间窗口。完整90.01秒FLAC的34,563,840字节PCM与来源散列相等，全部1055个编码音频负载也相等。报告 vfr-offset-media-validation.json。
- VFR-AUDIO-OBS：音频包时间戳有203项差异，最大2毫秒，首末时间均相同。普通容器原样复制为精确；将本次编码视频与原FLAC交给独立MKVToolNix重做同一最终混流，所有音频包字段与程序成品完全相同，确认差异可在外部工具层复现。未以放宽断言冒充逐包时间完全相等，也未重编码或改写已验证成品。报告 vfr-audio-{timestamp-copy,final-mux}-control.json，保留为非累计时间量化观察。

- FINAL-AUDIT-01：完成总覆盖审计，30个一级输入均为 pass_with_notes；芙莉莲三集共105,571视频包、最新Windows GUI、VFR/预设及36张发布截图报告均核对。代表功能完成，不把未获得的真实混合HDR、虚拟机Vulkan或MyGO自动布局记为通过。完整审计与证据散列清单见 reports/final-coverage-audit.json。

## 问题与暂缓项

- **MyGO 3.1布局**：来源解码与自动转换仍标4.0，不能认定已自动正确处理。完整PCM与四个声道散列均相等；仅改 FLAC 声道掩码的3.1副本及 MKA 已验证，位于 `Fixtures/mygo-channel-mask`。不对所有四声道来源应用猜测规则。见 MYGO-02/03。
- **Windows 虚拟机图形环境**：VirtIO/RDP 没有可用 Vulkan，placebo 去色带和 VSEdit 实际预览受限；关闭该项后 Windows 适用编码流程通过，五项滤镜同时执行已在 Docker 验证。mpv 音频听感由用户自行检查，未宣称已试听通过。
- **HDR 来源与支持范围**：尚无同时携带真实 DV 和 HDR10+ 的混合来源；HDR10+ 使用上游259帧完整黑场素材，仅验证元数据流程，不能视作4K实景画质测试。x265 12-bit 保留 DV 不受支持，已以前置检查限定 Main10；SVT-AV1 12-bit 按文档不适用。
- **getnative / PSNR**：已修复样本支持度偏置、空白帧和检测隐式色彩转换；来源逐集不同的原生分辨率仍可能合理，不要求算法强行统一。PSNR保持30dB；正常和反相单帧对照通过，不据有限样本保证所有素材零误报。
- **音频边界量化**：VFR 成品203个音频包时间点最多差2毫秒、首末不变；完整PCM和1055包编码负载精确相同。独立 MKVToolNix 最终混流完全复现，保留工具层非累计时间量化观察。菜单/章节边界末尾少量全零采样裁切详见对应报告。
- **菜单与其他来源观察**：三种循环处理已通过实际媒体检查；原MPLS显示时长不等于成品时长，先前由长菜单显示推断执行异常的判断已撤回。近似但不完全相同SP是否额外去重、没有同版BDrip参照及少量无法复现的初次界面状态，按用户规则暂缓，不添加推测性修复。
- **其他 Windows 工具差异**：AV1 chroma_location 警告与版本差异、tsMuxer 仅 mux 写共享盘限制保留；应用实际 demux 路径通过。共享盘回收站提示选择“否”，没有清空回收站。上述情况不扩展为本轮必需的新功能。
