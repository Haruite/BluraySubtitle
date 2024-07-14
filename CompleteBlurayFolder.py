# 补全蓝光目录

import os
import shutil


src_paths = r'E:\BDMV', r'F:\BDMV', r'G:\BDMV', r'H:\BDMV'
# 填蓝光原盘所在的文件夹，多个用逗号隔开


for src_path in src_paths:
    for root, dirs, files in os.walk(src_path):
        if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
            bdmv = os.path.join(root, 'BDMV')
            backup = os.path.join(bdmv, 'BACKUP')
            if os.path.exists(backup):
                for item in os.listdir(backup):
                    if not os.path.exists(os.path.join(bdmv, item)):
                        if os.path.isdir(os.path.join(backup, item)):
                            shutil.copytree(os.path.join(backup, item), os.path.join(bdmv, item))
                        else:
                            shutil.copy(os.path.join(backup, item), os.path.join(bdmv, item))
            for item in 'AUXDATA', 'BDJO', 'JAR', 'META':
                if not os.path.exists(os.path.join(bdmv, item)):
                    os.mkdir(os.path.join(bdmv, item))
