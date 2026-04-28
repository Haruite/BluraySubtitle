"""Auto-generated split target: encode_and_audio_tasks."""
import os
import re
import subprocess
import sys
from typing import Optional

import pycountry

from .service_base import BluraySubtitleServiceBase
from ...core import X265_PATH, MKV_INFO_PATH, MKV_EXTRACT_PATH, mkvtoolnix_ui_language_arg
from ...core.i18n import translate_text
from ...exports.utils import print_exc_terminal, get_vspipe_context, force_remove_file

MIGRATE_METHODS = ['flac_task', 'encode_task', 'extract_lossless']

class EncodeAudioTasksMixin(BluraySubtitleServiceBase):
    def flac_task(self, output_file, dst_folder, i, source_file: Optional[str] = None):
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i,
                                                                         source_file=source_file)
        if flac_files:
            src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
            same_mkv = os.path.normpath(output_file) == src_mkv
            output_file1 = (os.path.splitext(output_file)[0] + '.tmp.mkv') if same_mkv else output_file
            remux_cmd = self.generate_remux_cmd(track_count, track_info, flac_files, output_file1, src_mkv)
            if self.sub_files and len(self.sub_files) >= i and i > -1:
                lang = 'chi'
                try:
                    langs = getattr(self, 'episode_subtitle_languages', None) or []
                    if 0 <= (i - 1) < len(langs) and str(langs[i - 1]).strip():
                        lang = str(langs[i - 1]).strip()
                except Exception:
                    lang = 'chi'
                remux_cmd += f' --language 0:{lang} "{self.sub_files[i - 1]}"'
            print(f'{translate_text("Mux command:")}{remux_cmd}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            if same_mkv:
                if os.path.getsize(output_file1) > os.path.getsize(output_file):
                    os.remove(output_file1)
                else:
                    os.remove(output_file)
                    os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)
        self._extract_single_audio_from_mka(output_file)

    def encode_task(self, output_file, dst_folder, i, vpy_path: str, vspipe_mode: str, x265_mode: str, x265_params: str,
                    sub_pack_mode: str, source_file: Optional[str] = None):
        src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)

        def update_vpy_script():
            if not os.path.exists(vpy_path):
                return
            try:
                with open(vpy_path, 'r', encoding='utf-8') as fp:
                    lines = fp.readlines()
            except Exception:
                print_exc_terminal()
                return

            mkv_real_path = os.path.normpath(src_mkv)
            subtitle_real_path = None
            if self.sub_files and len(self.sub_files) >= i and i > -1:
                subtitle_real_path = os.path.normpath(self.sub_files[i - 1])

            def _to_py_r_string(value: str) -> str:
                return 'r"' + value.replace('"', '\\"') + '"'

            updated = False
            new_lines = []
            for line in lines:
                stripped = line.lstrip()
                if stripped.startswith('a ='):
                    indent = line[:len(line) - len(stripped)]
                    comment = ''
                    if '#' in stripped:
                        comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                    new_lines.append(f'{indent}a = {_to_py_r_string(mkv_real_path)}{comment}\n')
                    updated = True
                    continue

                if subtitle_real_path and stripped.startswith('sub_file =') and not stripped.startswith('#'):
                    indent = line[:len(line) - len(stripped)]
                    comment = ''
                    if '#' in stripped:
                        comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                    new_lines.append(f'{indent}sub_file = {_to_py_r_string(subtitle_real_path)}{comment}\n')
                    updated = True
                    continue

                new_lines.append(line)

            if not updated:
                return
            try:
                with open(vpy_path, 'w', encoding='utf-8') as fp:
                    fp.writelines(new_lines)
            except Exception:
                print_exc_terminal()

        update_vpy_script()

        def cleanup_lwi_for_source(source_path: str):
            for suffix in ('.lwi', '.lwi.lock'):
                try:
                    p = source_path + suffix
                    if os.path.exists(p) and os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    print_exc_terminal()

        if vspipe_mode == 'bundle':
            vspipe_exe, vspipe_env = get_vspipe_context()
        else:
            vspipe_exe, vspipe_env = 'vspipe.exe', None
            if sys.platform != 'win32':
                vspipe_exe = 'vspipe'
        if x265_mode == 'bundle':
            x265_exe = X265_PATH
        else:
            x265_exe = 'x265.exe' if sys.platform == 'win32' else 'x265'
        hevc_file = os.path.join(dst_folder, os.path.splitext(os.path.basename(output_file))[0] + '.hevc')
        cmd = f'"{vspipe_exe}" --y4m "{vpy_path}" - | "{x265_exe}" {x265_params or ""} --y4m -D 10 -o "{hevc_file}" -'
        print(f'{translate_text("Encode command:")}{cmd}')
        subprocess.Popen(cmd, shell=True, env=vspipe_env).wait()
        cleanup_lwi_for_source(src_mkv)
        track_count, track_info, flac_files = self.process_audio_to_flac(output_file, dst_folder, i,
                                                                         source_file=src_mkv)
        if flac_files or os.path.exists(hevc_file):
            same_mkv = os.path.normpath(output_file) == src_mkv
            output_file1 = (os.path.splitext(output_file)[0] + '.tmp.mkv') if same_mkv else output_file
            if not same_mkv and os.path.exists(output_file1):
                force_remove_file(output_file1)
            remux_cmd = self.generate_remux_cmd(track_count, track_info, flac_files, output_file1, src_mkv,
                                                hevc_file=hevc_file if os.path.exists(hevc_file) else None)
            if sub_pack_mode == 'soft':
                if self.sub_files and len(self.sub_files) >= i and i > -1:
                    lang = 'chi'
                    try:
                        langs = getattr(self, 'episode_subtitle_languages', None) or []
                        if 0 <= (i - 1) < len(langs) and str(langs[i - 1]).strip():
                            lang = str(langs[i - 1]).strip()
                    except Exception:
                        lang = 'chi'
                    remux_cmd += f' --language 0:{lang} "{self.sub_files[i - 1]}"'
            print(f'{translate_text("Mux command:")}{remux_cmd}')
            subprocess.Popen(remux_cmd, shell=True).wait()
            if same_mkv:
                if os.path.getsize(output_file1) > os.path.getsize(output_file):
                    os.remove(output_file1)
                else:
                    os.remove(output_file)
                    os.rename(output_file1, output_file)
            for flac_file in flac_files:
                os.remove(flac_file)
            if os.path.exists(hevc_file):
                os.remove(hevc_file)
        cleanup_lwi_for_source(src_mkv)

    def extract_lossless(self, mkv_file: str, dolby_truehd_tracks: list[int], output_base: Optional[str] = None) -> \
    tuple[int, dict[int, str]]:
        if sys.platform == 'win32':
            process = subprocess.Popen(f'"{MKV_INFO_PATH}" "{mkv_file}" --ui-language en',
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='ignore', shell=True)
        else:
            process = subprocess.Popen(f'"{MKV_INFO_PATH}" "{mkv_file}" --ui-language en_US',
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', errors='ignore', shell=True)
        stdout, stderr = process.communicate()

        track_info = {}
        track_count = 0
        track_suffix_info = {}
        for line in stdout.splitlines():
            if line.startswith('|  + Track number: '):
                track_id = int(re.findall(r'\d+', line.removeprefix('|  + Track number: '))[0]) - 1
                track_count = max(track_count, track_id)
            if line.startswith('|  + Codec ID: '):
                codec_id = line.removeprefix('|  + Codec ID: ').strip()
                code_id_to_stream_type = {'A_DTS': 'DTS', 'A_PCM/INT/LIT': 'LPCM', 'A_PCM/INT/BIG': 'LPCM',
                                          'A_TRUEHD': 'TRUEHD', 'A_MLP': 'TRUEHD'}
                stream_type = code_id_to_stream_type.get(codec_id)
            if line.startswith('|  + Language (IETF BCP 47): '):
                bcp_47_code = line.removeprefix('|  + Language (IETF BCP 47): ').strip()
                language = pycountry.languages.get(alpha_2=bcp_47_code.split('-')[0])
                if language is None:
                    language = pycountry.languages.get(alpha_3=bcp_47_code.split('-')[0])
                if language:
                    lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None))
                else:
                    lang = 'und'
                if stream_type in ('LPCM', 'DTS', 'TRUEHD'):
                    if track_id not in dolby_truehd_tracks:
                        track_info[track_id] = lang
                        if stream_type == 'LPCM':
                            track_suffix_info[track_id] = 'wav'
                        elif stream_type == 'DTS':
                            track_suffix_info[track_id] = 'dts'
                        else:
                            track_suffix_info[track_id] = 'thd'

        if track_info:
            extract_info = []
            base = output_base if output_base else mkv_file[:-4]
            for track_id, lang in track_info.items():
                extract_info.append(
                    f'{track_id}:"{base}.track{track_id}.{track_suffix_info[track_id]}"')
            extract_cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_file}" tracks {" ".join(extract_info)}'
            print(f'{translate_text("Extracting lossless tracks, command: ")}{extract_cmd}')
            subprocess.Popen(extract_cmd, shell=True).wait()

        return track_count, track_info
