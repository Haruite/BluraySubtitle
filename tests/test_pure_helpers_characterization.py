"""Characterization tests for shared parsers and encoder option helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile

from src.runtime.sp import (
    filter_m2ts_file_detail_by_basenames,
    m2ts_file_detail_segments_contained_in,
    parse_m2ts_file_detail_segments,
)
from src.runtime.audio_conversion import (
    _is_lossless_audio_track,
    is_immersive_audio_codec,
)
from src.runtime.services_split.encode_and_audio_tasks import (
    _normalize_x264_extra_for_bit_depth,
)
from src.runtime.services_split.media_info_and_track_mapping import (
    MediaInfoTrackMappingMixin,
)
from src.runtime.services_split.misc_workflows import _movie_sp_duration_matches_main



class M2tsDetailTests(unittest.TestCase):
    detail = (
        "00001.m2ts(00:00:01.500-00:02:03.250),"
        "00002.m2ts(00:00:00.000-00:00:01.250)"
    )

    def test_shared_parser_preserves_the_current_result(self) -> None:
        expected = [
            ("00001.m2ts", 1.5, 123.25),
            ("00002.m2ts", 0.0, 1.25),
        ]
        self.assertEqual(parse_m2ts_file_detail_segments(self.detail), expected)
        self.assertEqual(parse_m2ts_file_detail_segments("invalid"), [])

    def test_shared_containment_preserves_the_current_result(self) -> None:
        episode = "00001.m2ts(00:00:01.000-00:02:04.000)"
        contained = "00001.m2ts(00:00:01.500-00:02:03.250)"
        outside = "00001.m2ts(00:00:00.000-00:02:03.250)"
        wrong_clip = "00002.m2ts(00:00:01.500-00:02:03.250)"

        self.assertTrue(m2ts_file_detail_segments_contained_in(contained, episode))
        self.assertFalse(m2ts_file_detail_segments_contained_in(outside, episode))
        self.assertFalse(m2ts_file_detail_segments_contained_in(wrong_clip, episode))
        self.assertFalse(m2ts_file_detail_segments_contained_in("", episode))

    def test_shared_filter_preserves_the_current_result(self) -> None:
        expected = "00002.m2ts(00:00:00.000-00:00:01.250)"
        self.assertEqual(filter_m2ts_file_detail_by_basenames(self.detail, ["00002.m2ts"]), expected)
        self.assertEqual(filter_m2ts_file_detail_by_basenames(self.detail, []), self.detail)

    def test_movie_duration_match_uses_a_strict_one_millisecond_tolerance(self) -> None:
        self.assertTrue(_movie_sp_duration_matches_main(100.0009, 100.0))
        self.assertFalse(_movie_sp_duration_matches_main(100.001, 100.0))
        self.assertFalse(_movie_sp_duration_matches_main("unknown", 100.0))


class EncoderOptionTests(unittest.TestCase):

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

    def test_audio_conversion_only_targets_the_supported_lossless_families(self) -> None:
        def track(codec_id: str, codec: str = '') -> dict[str, object]:
            return {'codec': codec, 'properties': {'codec_id': codec_id}}

        self.assertTrue(_is_lossless_audio_track(track('A_TRUEHD')))
        self.assertTrue(
            _is_lossless_audio_track(track('A_DTS', 'DTS-HD Master Audio'))
        )
        self.assertFalse(_is_lossless_audio_track(track('A_DTS', 'DTS')))
        self.assertFalse(
            _is_lossless_audio_track(track('A_DTS', 'DTS-HD High Resolution Audio'))
        )
        self.assertTrue(_is_lossless_audio_track(track('A_FLAC')))
        self.assertTrue(_is_lossless_audio_track(track('A_PCM/INT/LIT')))
        self.assertFalse(_is_lossless_audio_track(track('A_AC3')))
        self.assertFalse(_is_lossless_audio_track(track('A_EAC3')))
        self.assertFalse(_is_lossless_audio_track(track('A_AAC/MPEG4/LC')))
        self.assertFalse(_is_lossless_audio_track(track('A_OPUS')))
        self.assertTrue(is_immersive_audio_codec('dts', 'DTS-HD MA + DTS:X'))
        self.assertTrue(is_immersive_audio_codec('truehd', 'TrueHD', 'Atmos'))


class SilentAudioAnalysisTests(unittest.TestCase):
    def test_numpy_rms_matches_the_retained_relative_db_behavior(self) -> None:
        sample_rate = 22050
        audio = np.zeros(sample_rate * 2, dtype=np.float32)
        audio[:2048] = 0.5
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            soundfile.write(audio_path, audio, sample_rate, subtype="FLOAT")

            silent, average_db = MediaInfoTrackMappingMixin._is_silent_audio_file(
                str(audio_path),
                threshold_db=-60.0,
            )

        self.assertTrue(silent)
        self.assertLess(average_db, -60.0)


if __name__ == "__main__":
    unittest.main()
