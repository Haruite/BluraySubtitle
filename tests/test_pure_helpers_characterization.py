"""Characterization tests for duplicated parsers and encoder option helpers."""

from __future__ import annotations

import unittest

from src.runtime.gui_runtime_split.output_and_tracks import (
    filter_m2ts_file_detail_by_basenames,
    m2ts_file_detail_segments_contained_in,
    parse_m2ts_file_detail_segments,
)
from src.runtime.audio_conversion import _is_lossless_audio_track
from src.runtime.services_split.encode_and_audio_tasks import (
    _format_encoder_cmd_for_echo,
    _normalize_x264_extra_for_bit_depth,
    _split_x265_extra_args,
)
from src.runtime.services_split.misc_workflows import (
    _filter_m2ts_file_detail_by_basenames,
    _m2ts_file_detail_segments_contained_in,
    _parse_m2ts_file_detail_segments,
    _movie_sp_duration_matches_main,
)


class M2tsDetailTests(unittest.TestCase):
    detail = (
        "00001.m2ts(00:00:01.500-00:02:03.250),"
        "00002.m2ts(00:00:00.000-00:00:01.250)"
    )

    def test_gui_and_service_parsers_have_the_same_current_result(self) -> None:
        expected = [
            ("00001.m2ts", 1.5, 123.25),
            ("00002.m2ts", 0.0, 1.25),
        ]
        self.assertEqual(parse_m2ts_file_detail_segments(self.detail), expected)
        self.assertEqual(_parse_m2ts_file_detail_segments(self.detail), expected)
        self.assertEqual(parse_m2ts_file_detail_segments("invalid"), [])
        self.assertEqual(_parse_m2ts_file_detail_segments("invalid"), [])

    def test_gui_and_service_containment_have_the_same_current_result(self) -> None:
        episode = "00001.m2ts(00:00:01.000-00:02:04.000)"
        contained = "00001.m2ts(00:00:01.500-00:02:03.250)"
        outside = "00001.m2ts(00:00:00.000-00:02:03.250)"
        wrong_clip = "00002.m2ts(00:00:01.500-00:02:03.250)"

        for helper in (
            m2ts_file_detail_segments_contained_in,
            _m2ts_file_detail_segments_contained_in,
        ):
            self.assertTrue(helper(contained, episode))
            self.assertFalse(helper(outside, episode))
            self.assertFalse(helper(wrong_clip, episode))
            self.assertFalse(helper("", episode))

    def test_gui_and_service_filters_have_the_same_current_result(self) -> None:
        expected = "00002.m2ts(00:00:00.000-00:00:01.250)"
        self.assertEqual(filter_m2ts_file_detail_by_basenames(self.detail, ["00002.m2ts"]), expected)
        self.assertEqual(_filter_m2ts_file_detail_by_basenames(self.detail, ["00002.m2ts"]), expected)
        self.assertEqual(filter_m2ts_file_detail_by_basenames(self.detail, []), self.detail)
        self.assertEqual(_filter_m2ts_file_detail_by_basenames(self.detail, []), self.detail)

    def test_movie_duration_match_uses_a_strict_one_millisecond_tolerance(self) -> None:
        self.assertTrue(_movie_sp_duration_matches_main(100.0009, 100.0))
        self.assertFalse(_movie_sp_duration_matches_main(100.001, 100.0))
        self.assertFalse(_movie_sp_duration_matches_main("unknown", 100.0))


class EncoderOptionTests(unittest.TestCase):
    def test_x265_extra_args_split_empty_and_simple_options(self) -> None:
        self.assertEqual(_split_x265_extra_args(""), [])
        self.assertEqual(
            _split_x265_extra_args("--preset slow --crf 18"),
            ["--preset", "slow", "--crf", "18"],
        )

    def test_x264_profile_is_normalized_for_output_bit_depth(self) -> None:
        source = ["--preset", "slow"]
        self.assertEqual(
            _normalize_x264_extra_for_bit_depth(source, "10"),
            ["--profile", "high10", "--preset", "slow"],
        )
        self.assertEqual(source, ["--preset", "slow"])
        self.assertEqual(
            _normalize_x264_extra_for_bit_depth(["--profile", "high10"], "8"),
            ["--profile", "high"],
        )
        self.assertEqual(
            _normalize_x264_extra_for_bit_depth(["--profile=high"], "10"),
            ["--profile=high10"],
        )

    def test_encoder_echo_quotes_executable_outputs_and_spaced_values(self) -> None:
        command = [
            r"C:\Program Files\x265.exe",
            "--preset",
            "slow",
            "-o",
            r"C:\Output Folder\video.hevc",
            "-b",
            "10",
            "input value",
        ]
        self.assertEqual(
            _format_encoder_cmd_for_echo(command),
            '"C:\\Program Files\\x265.exe" --preset slow '
            '-o "C:\\Output Folder\\video.hevc" -b "10" "input value"',
        )

    def test_audio_conversion_only_targets_the_supported_lossless_families(self) -> None:
        def track(codec_id: str, codec: str = '') -> dict[str, object]:
            return {'codec': codec, 'properties': {'codec_id': codec_id}}

        self.assertTrue(_is_lossless_audio_track(track('A_TRUEHD')))
        self.assertTrue(_is_lossless_audio_track(track('A_DTS')))
        self.assertTrue(_is_lossless_audio_track(track('A_FLAC')))
        self.assertTrue(_is_lossless_audio_track(track('A_PCM/INT/LIT')))
        self.assertFalse(_is_lossless_audio_track(track('A_AC3')))
        self.assertFalse(_is_lossless_audio_track(track('A_EAC3')))
        self.assertFalse(_is_lossless_audio_track(track('A_AAC/MPEG4/LC')))
        self.assertFalse(_is_lossless_audio_track(track('A_OPUS')))


if __name__ == "__main__":
    unittest.main()
