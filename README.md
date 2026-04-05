# BluraySubtitle
本工具用于将分集的字幕合并成适合蓝光播放的字幕。  
因为原盘一般都是几集整一个盘，连续播放，主播放列表一般有2-6集不等。而字幕组制作的字幕基本上都是按单集划分，如果想用 PowerDVD 或者 JMC 看原盘的话就面临字幕不匹配的问题，解决方法只能是合并字幕，而这个操作手动做事很费时间的。所以我研究了这个问题，写了一个全自动合并字幕的脚本，只需要选择原盘所在的文件夹和字幕所在的文件夹，就能合成原盘播放所需的字幕。  
代码：https://github.com/Haruite/BluraySubtitle/blob/main/BluraySubtitle.py

### Feature:
1. 支持原盘为 iso 文件 (仅限 Windows 系统 Windows 8 及以上可用) 
2. 支持 .ass/.ssa/.srt 格式的字幕
3. 可以选择主播放列表
4. 可以预览播放
5. 支持勾选、拖动字幕
6. 支持编辑字幕
7. 支持调整字幕偏移
8. 补全蓝光目录
9. 支持给 mkv 文件添加章节（两种方式，直接编辑或者混流）
10. 支持原盘 remux
11. 支持 Windows 和 Linux 系统

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
