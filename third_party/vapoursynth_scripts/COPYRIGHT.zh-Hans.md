# VapourSynth Python 滤镜脚本版权与来源说明

[English](COPYRIGHT.md) | 简体中文

这些第三方脚本的著作权归各自上游作者与贡献者所有。BluraySubtitle 根目录的 MIT 许可证不替代其原有许可，也不授予上游未授予的权利。各函数内部保留的署名和来源引用同样适用。

## 引入快照

本快照于 2026-10-28 从 [AmusementClub/tools 2025H1p](https://github.com/AmusementClub/tools/releases/tag/2025H1p) 发布资源 `vapoursynth_portable_25H1.1p_cpu.7z` 所分发的 `VapourSynthScripts` 文件引入。该分发包用于说明这些副本的来源，不代表所有脚本采用同一种许可证。安装和打包直接读取仓库中的文件，不再为 Python 脚本下载该压缩包。

引入时添加了来源注释，将换行统一为 CRLF，并移除了行尾空白。其中，MIR 修改的 `havsfunc.py` 在文件头标记为 `33-7f0a9a7-AC-4`，基于提交 `7f0a9a7a37b60a05b9f408024d203e511e544a61`；分发包的更新记录将 `muvsfunc.py` 对应修订标记为 `634d58c0f6464b1454813153aba85c78e17ab3a0`。

## 作者、来源与许可依据

| 文件 | 署名与上游来源 | 许可依据 |
| --- | --- | --- |
| `adjust.py` | dubhater 与贡献者；[vapoursynth-adjust](https://github.com/dubhatervapoursynth/vapoursynth-adjust) | 上游 README 声明使用 WTFPL，未注明版本。附有副本 [adjust-readme.rst](licenses/adjust-readme.rst)。 |
| `dfttest2.py` | AmusementClub 与贡献者；[vs-dfttest2 v9](https://github.com/AmusementClub/vs-dfttest2/tree/v9)；脚本版本 `0.4.0` | 上游提供 GNU GPL 第 3 版文本，附于 [GPL-3.0.txt](licenses/GPL-3.0.txt)。 |
| `havsfunc.py` | HolyWu 与贡献者，由 MIR 修改；[原始修订](https://github.com/HomeOfVapourSynthEvolution/havsfunc/tree/7f0a9a7a37b60a05b9f408024d203e511e544a61) | 原始修订提供 [Unlicense](licenses/havsfunc-Unlicense.txt)。本快照中的 MIR 修改没有单独的许可声明。 |
| `MCDenoise.py` | Mystery Keeper；[TempLinearApproximate 上游](https://bitbucket.org/mystery_keeper/templinearapproximate-vapoursynth/) | 所复制的脚本没有版权或许可证文件头。作者的[发布公告](https://forum.doom9.org/archive/index.php/t-169782.html)说明 TempLinearApproximate 改用 MIT，但未能取得专门随该脚本提供的完整许可声明。 |
| `mirvsfunc.py` | MIR / AmusementClub 与贡献者；[vapoursynth-script](https://github.com/AmusementClub/vapoursynth-script)；脚本版本 `0.1.3` | 所复制文件和查阅的上游仓库中均未找到许可声明。 |
| `muvsfunc.py` | WolframRhodium 与贡献者；[分发包记录的修订](https://github.com/WolframRhodium/muvsfunc/tree/634d58c0f6464b1454813153aba85c78e17ab3a0) | 所复制文件和查阅的上游仓库中均未找到许可声明。 |
| `muvsfunc_numpy.py` | WolframRhodium 与贡献者；[muvsfunc collections](https://github.com/WolframRhodium/muvsfunc/tree/master/Collections) | 所复制文件和查阅的上游仓库中均未找到许可声明。复用实现的内部署名已保留。 |
| `mvsfunc.py` | mawen1250 与贡献者；[mvsfunc](https://github.com/HomeOfVapourSynthEvolution/mvsfunc) | 所复制文件和查阅的上游仓库中均未找到许可声明。 |
| `nnedi3_resample.py` | HomeOfVapourSynthEvolution 贡献者；[nnedi3_resample](https://github.com/HomeOfVapourSynthEvolution/nnedi3_resample) | 所复制文件和查阅的上游仓库中均未找到许可声明。 |
| `vsmlrt.py` | AmusementClub 与贡献者；[vs-mlrt](https://github.com/AmusementClub/vs-mlrt)；脚本版本 `3.22.35` | 上游提供 GNU GPL 第 3 版文本，附于 [GPL-3.0.txt](licenses/GPL-3.0.txt)。模型与推理后端具有独立于该 Python 脚本的许可。 |
| `vsTAAmbk.py` | HomeOfVapourSynthEvolution 贡献者；[vsTAAmbk](https://github.com/HomeOfVapourSynthEvolution/vsTAAmbk) | 所复制文件和查阅的上游仓库中均未找到许可声明。 |

许可未注明不等于 MIT、公有领域或无限制使用声明。本文件记录已取得的依据，不补充缺失的授权，也不重新许可上游修改。

## 分发位置

Windows 和 Linux 安装脚本将 `.py` 文件安装到选定的 VapourSynth Python 搜索目录，并将本说明及许可文本安装到该目录下的 `licenses/vapoursynth_scripts/`。Docker 将相同文件安装到其 Python `dist-packages` 目录。Windows 程序包将脚本放在共用 Python 运行时旁，说明和许可文本位于 `legal/vapoursynth_scripts/`。
