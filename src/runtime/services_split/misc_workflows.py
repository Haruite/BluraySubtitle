"""Auto-generated split target: misc_workflows."""
import os
import threading
from typing import Optional

from src.bdmv import Chapter
from src.core import DEFAULT_APPROX_EPISODE_DURATION_SECONDS
from src.exports.utils import get_time_str
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled


class MiscWorkflowsMixin(BluraySubtitleServiceBase):
        @staticmethod
        def _group_selected_mpls_by_folder_runs(selected_mpls: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
            if not selected_mpls:
                return []
            groups: list[list[tuple[str, str]]] = []
            cur_fn = os.path.normpath(str(selected_mpls[0][0]))
            cur: list[tuple[str, str]] = [selected_mpls[0]]
            for t in selected_mpls[1:]:
                fn = os.path.normpath(str(t[0]))
                if fn == cur_fn:
                    cur.append(t)
                else:
                    groups.append(cur)
                    cur_fn = fn
                    cur = [t]
            groups.append(cur)
            return groups

        def _volume_configuration_no_sub_files(
                self,
                volume_selected: list[tuple[str, str]],
                cancel_event: Optional[threading.Event] = None,
        ) -> dict[int, dict[str, int | str]]:
            """Episode rows for one disc's selected main MPLS list (no subtitle files). Keys 0..n-1 local."""
            if self.sub_files:
                raise ValueError('_volume_configuration_no_sub_files requires empty sub_files')
            if not volume_selected:
                return {}
            configuration: dict[int, dict[str, int | str]] = {}
            sub_index = 0
            approx_end_time = float(
                getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
                or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
            sub_max_end: list[float] = []
            folder_to_bdmv_index: dict[str, int] = {}
            for i, f in enumerate(getattr(self, 'bluray_folders', []) or []):
                try:
                    folder_to_bdmv_index[os.path.normpath(str(f))] = int(i + 1)
                except Exception:
                    pass
            for folder, selected_mpls_no_ext in volume_selected:
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                folder_n = os.path.normpath(str(folder))
                if folder_n not in folder_to_bdmv_index:
                    folder_to_bdmv_index[folder_n] = len(folder_to_bdmv_index) + 1
                bdmv_index = folder_to_bdmv_index[folder_n]
                disc_output_name = self._resolve_disc_output_name(selected_mpls_no_ext)
                chapter = Chapter(selected_mpls_no_ext + '.mpls')
                start_time = 0
                sub_end_time = approx_end_time
                left_time = chapter.get_total_time()
                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                            'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0',
                                            'disc_output_name': disc_output_name}
                j = 1
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    chapter_num = len(play_item_marks or [])
                    if play_item_marks:
                        play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                        time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                        if time_shift > sub_end_time - 300:
                            if left_time > approx_end_time - 180:
                                sub_index += 1
                                sub_end_time = (time_shift + approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift),
                                                            'disc_output_name': disc_output_name}

                        if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                            k = j
                            for mark in play_item_marks[1:]:
                                k += 1
                                time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_index += 1
                                    sub_end_time = (time_shift + approx_end_time)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                                'bdmv_index': bdmv_index, 'chapter_index': k,
                                                                'offset': get_time_str(time_shift),
                                                                'disc_output_name': disc_output_name}

                    j += chapter_num
                    start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

                sub_index += 1
            return configuration
