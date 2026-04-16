# BluraySubtitle
本工具包含多个功能。  
1.合并字幕  
2.给mkv添加章节  
3.原盘remux   
4.原盘压制  

### Feature:
1. （所有功能）支持一键操作，无需设置
2. （所有功能）可以选择主播放列表
3. （所有功能）可以预览播放，支持 mpv
4. （所有功能）支持选择每集的切割点
5. （所有功能）支持 Windows 和 Linux 系统
6. （所有功能）支持 Docker
7. （合并字幕）支持原盘为 iso 文件 (仅限 Windows 系统 Windows 8 及以上可用)
8. （合并字幕）支持 .ass/.ssa/.srt 格式的字幕
9. （合并字幕）支持勾选、拖动字幕
10. （合并字幕）支持编辑字幕
11. （合并字幕）补全蓝光目录
12. （添加章节）支持两种方式给 mkv 文件添加章节，直接编辑或者混流
13. （原盘 remux & 压制）自动获取输出文件名
14. （原盘 remux & 压制）自动获取封面
15. （原盘 remux & 压制）压缩无损音轨
16. （原盘 remux & 压制）保留原盘章节
17. （原盘 remux & 压制）保留所有时长 >=30s 的特典
18. （原盘 remux & 压制）删除空音轨和重复音轨
19. （原盘 remux & 压制）识别并将音轨转换到真实位深，修复音轨延迟
20. （原盘压制）支持给每集和每个特典定制 vs 脚本
21. （原盘压制）支持预览 vs 脚本
22. （原盘压制）支持外挂/内挂/内嵌字幕
23. 支持 Docker，可以手动构建或者从 DockerHub 拉取
24. 附带 Linux 构建环境脚本，服务器一键构建压制环境

### 使用教程（部分图片视频可能源于早期版本，仅供参考）:
#### 合并字幕通用方法：
对于大多数的原盘以及对应的字幕，简单三步即可，如图所示
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-27_22-16-28.png)
也可参考视频
[![点击播放视频](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/%E7%A4%BA%E4%BE%8B1-%E7%94%9F%E6%88%90%E5%90%88%E5%B9%B6%E5%AD%97%E5%B9%95.mp4_000045.020.png)](https://sbx.mysmy.top/u2/videos/%E7%A4%BA%E4%BE%8B1-%E7%94%9F%E6%88%90%E5%90%88%E5%B9%B6%E5%AD%97%E5%B9%95.mp4)
注意，linux下拖入字幕文件夹后，字幕排列是乱序的，需要点击 path 栏使其排序
#### 合并字幕特殊情况：
1. 存在特典盘或字幕顺序与原盘不对应  
例如：  
原盘：U2#54711  
字幕：https://bbs.acgrip.com/forum.php?mod=viewthread&tid=11102  
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_20-12-52.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_20-10-39.png)
2. 因为某些原因或错误字幕持续时间超长，通常表现为最后一条字幕没有对应的BDMV，这时需要检查字幕table的duratuion列，找出时间超长的字幕并修改  
例如：  
原盘：U2#21685  
字幕：https://bbs.acgrip.com/forum.php?mod=viewthread&tid=6497  
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-27_22-34-23.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-27_22-37-46.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-27_22-41-10.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-27_22-59-17.png)
3. 主播放列表选择错误，通常字幕会发生错乱，这时需要用 play 列确定并选择正确的主播放列表  
例如：  
原盘：U2#52355  
字幕：https://bbs.acgrip.com/forum.php?mod=viewthread&tid=10490 喵萌奶茶屋  
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-25-04.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-28-56.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-32-29.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-33-57.png)
5. 因为某些原因，字幕偏移不对，这时需要手动调整 chapter_index 列  
例如：  
原盘：U2#47590  
字幕：https://github.com/Nekomoekissaten-SUB/Nekomoekissaten-Storage/releases/download/subtitle_pkg/ODDTAXI_TV_BD_Subs.7z
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-36-15.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-38-54.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-46-33.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/2025-03-28_19-56-32.png)  
#### mkv 文件添加章节  
操作步骤如下：  
1. 下载原盘（可以下载时只下载 playlist 文件夹中的 mpls 文件，注意保持目录结构）
2. 拖入原盘文件夹
3. 拖入 mkv 所在的文件夹，注意文件夹中应当只有需要添加章节的 mkv 视频，其他视频需要暂时移出
4. （视情况而定，大部分时候不需要）选择 info 栏的 main 按钮，保证选择对的主播放列表
5. 点击底部添加章节按钮，等待完成  
参考视频如下
[![点击播放视频](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/%E7%A4%BA%E4%BE%8B2-mkv%E6%96%87%E4%BB%B6%E6%B7%BB%E5%8A%A0%E7%AB%A0%E8%8A%82.mp4_000110.135.png)](https://sbx.mysmy.top/u2/videos/%E7%A4%BA%E4%BE%8B2-mkv%E6%96%87%E4%BB%B6%E6%B7%BB%E5%8A%A0%E7%AB%A0%E8%8A%82.mp4)
#### 原盘 remux  
操作步骤如下：
1. 拖入原盘文件夹
2. （可选）拖入字幕文件夹
3. （视情况而定，大部分时候不需要）选择 info 栏的 main 按钮，保证选择对的主播放列表
4. （视情况而定，大部分时候不需要）调整 chapter_index 栏，保证文件正确切割
5. 点击开始 remux 按钮，会要求选择输出文件夹，选择后输出文件夹里面会建立一个和原盘文件夹同名的文件夹，里面存放 remux 文件  
参考视频如下  
[![点击播放视频](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/%E7%A4%BA%E4%BE%8B3-%E5%8A%A8%E6%BC%AB%E5%8E%9F%E7%9B%98remux.mp4_000312.462.png)](https://sbx.mysmy.top/u2/videos/%E7%A4%BA%E4%BE%8B3-%E5%8A%A8%E6%BC%AB%E5%8E%9F%E7%9B%98remux.mp4)
#### 原盘压制
和原盘 remux 大体相同，只不过多了一些选项。  
可以选择每集和各个特典的 vpy 文件，默认使用当前目录下的 vpy.vpy 文件  
可以编辑 vpy 文件（使用系统关联，Docker 是 gedit），预览 vpy 文件（使用 vsedit）  
压制功能区可以选择 vspipe 和 x265 的来源（程序自带或系统），可以选择和编辑 x265 参数，可以选择字幕封装方式（外挂或内挂或内嵌）  
设置完毕，点击开始压制按钮，选择输出文件夹，等待完成即可。  
#### Docker 支持
要生成 Docker 镜像，请在代码所在文件夹运行命令：  
```docker build -t bluray-subtitle-ubuntu .```  
运行容器推荐命令：  
```xhost +local:docker
sudo docker run -it --rm \
    --device /dev/snd \
    -e DISPLAY=$DISPLAY \
    -e LIBGL_ALWAYS_SOFTWARE=1 \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /run/media/clonmer/1856689756687800:/data \
    -v /run/user/$(id -u)/pulse:/run/user/1000/pulse \
    -e PULSE_SERVER=unix:/run/user/1000/pulse/native \
    --ipc=host \
    --shm-size=2gb \
bluray-subtitle-ubuntu
```
其中```/run/media/clonmer/1856689756687800```是宿主机文件目录(用于选择原盘、字幕等)，运行后将被挂载到 /data 目录  
这个命令可以保证 mpv 正常运行  
如果想进容器内部执行命令，或者使用 VapourSynth-Editor，可以执行：
```docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /run/media/clonmer/1856689756687800:/data \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $HOME:/data \
bluray-subtitle-ubuntu /bin/bash
```  
容器内安装的软件包括：mpv/ffmpeg/ffprobe/flac/x265/mkvtoolnix(-gui)/vapoursynth/vsedit/gedit/nautilus  
注意：容器内只携带常用的 vs 滤镜，如果需要用到其他滤镜需要自行编译  
已配置 Github Actions 推镜像送到 DockerHub，安装 Docker 后执行  
```docker pull haruite/bluraysubtitle:latest```  
即可拉取最新版镜像
#### linux 支持
build.sh 可以用于构建 linux 运行脚本所需要的环境，支持 Ubuntu 版本 >= 22.04 或者 Debain 版本 >= 12，已在 hetzner 服务器测试 Ubuntu 22.04 | Ubuntu 24.04 | Ubuntu 25.10 | Debian 12 | Debian 13 系统安装脚本， 均可一键安装成功，本地测试 Ubuntu 26.04 beata 版安装成功。建议通过 ssh 方式安装。如果想要服务器挂机压制，首先安装远程桌面，推荐 Ubuntu 25.10 + xfce4 + xrdp，系统可以先安装 Ubuntu 24.04 然后 do-release-upgrade 升级上去  
#### 软件界面截图
（运行于 Docker）  
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/%E6%88%AA%E5%9B%BE%202026-04-17%2004-39-28.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/%E6%88%AA%E5%9B%BE%202026-04-17%2004-41-20.png)
![示例图片](https://github.com/Haruite/BluraySubtitle/blob/main/pictures/%E6%88%AA%E5%9B%BE%202026-04-17%2004-42-02.png)
新版界面与旧版差异较大，主要表现在：  
1. 界面更加紧凑
2. 点击执行按钮后，不再弹出进度条，而是直接在按钮上显示进度，再次点击可以取消
3. 完成后不再显示弹窗，而是在界面最底部显示 10s 文字
4. 原盘以及字幕等水平滑条默认局右
### Q & A
Q: 为什么推荐 ssh 方式安装脚本？  
A: 远程安装会使用 tmux，输出更简洁，直接远程桌面在终端安装不会使用 tmux （其实是有些问题我解决不了）  
Q: 为什么 Docker 构建不使用 build.sh？  
A: 因为那样的话包太大  
Q: arm 架构的 MacBook 怎么使用 docker？  
A: build镜像命令```docker build --platform linux/amd64 -t bluray-subtitle-ubuntu .```。拉取镜像命令```docker pull --platform linux/amd64 haruite/bluraysubtitle:latest```。推荐启动命令```sudo docker run -it --rm \
    --platform linux/amd64 \
    -e DISPLAY=host.docker.internal:0 \
    -e LIBGL_ALWAYS_SOFTWARE=1 \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /Users/demo:/data \
    --ipc=host \
    --shm-size=2gb \
bluray-subtitle-ubuntu```  
Q: 压制功能有切黑边吗？  
A: 没有。因为切黑边涉及一些问题不好解决，如果有需求自行修改 vs 脚本  
Q: 压制一部 BDMV 时间太常，怎样测试压制功能？  
A: 编辑 vpy 文件，在末尾```res.set_output()```之前加上一行```res = res.std.Trim(first=0, length=720)  # (只压制720帧)```  
