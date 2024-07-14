# 添加字幕到 MPLS 目录下
import os
import shutil

from BluraySubtitle import Chapter


src_paths = r'E:\BDMV', r'F:\BDMV', r'G:\BDMV', r'H:\BDMV'
# 填蓝光原盘所在的文件夹，多个用逗号隔开


for src_path in src_paths:
    for root, dirs, files in os.walk(src_path):
        if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
            mpls_folder = os.path.join(root, 'BDMV', 'PLAYLIST')
            selected_mpls = None
            max_indicator = 0
            for mpls_file_name in os.listdir(mpls_folder):
                try:
                    mpls_file_path = os.path.join(mpls_folder, mpls_file_name)
                    chapter = Chapter(mpls_file_path)
                    indicator = chapter.get_total_time_no_repeat() * (1 + sum(map(len, chapter.mark_info.values())) / 5)
                    if indicator > max_indicator:
                        max_indicator = indicator
                        selected_mpls = mpls_file_path[:-5]
                except:
                    pass
            if selected_mpls:
                for suf in '.ass', '.ssa', '.srt':
                    if os.path.exists(root + suf):
                        shutil.copy(root + suf, selected_mpls + suf)
