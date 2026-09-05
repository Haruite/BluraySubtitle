import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.runtime.gui_runtime_split import vpy_edit_and_preview
from src.runtime.services_split import encode_and_audio_tasks
from src.vs_tools import getnative as getnative_module


class GetnativeCurveTests(unittest.TestCase):
    @staticmethod
    def _kernel_result(
        height: float,
        *,
        score: float = 10.0,
        evaluated_all: bool = True,
        curve_valid: bool = True,
    ) -> getnative_module._KernelResult:
        return getnative_module._KernelResult(
            name=f"kernel_{height}",
            heights=[height - 1, height, height + 1],
            errors=[2.0, 1.0, 2.0],
            best_height=height,
            best_score=score,
            evaluated_all=evaluated_all,
            curve_valid=curve_valid,
        )

    def test_kernel_consensus_requires_complete_valid_curves(self) -> None:
        results = [
            self._kernel_result(720),
            self._kernel_result(721, evaluated_all=False),
            self._kernel_result(722, curve_valid=False),
        ]

        self.assertIsNone(getnative_module._kernel_consensus(results, min_count=2))

        results.extend([self._kernel_result(721), self._kernel_result(722)])
        self.assertEqual(
            getnative_module._kernel_consensus(results, tol=2.0, min_count=3),
            721.0,
        )

    def test_fixed_540_band_and_scaled_curve_tail_are_excluded(self) -> None:
        for height in (535.0, 540.0, 545.0, 1040.01, 1058.0):
            with self.subTest(height=height):
                self.assertTrue(getnative_module._is_banned_height(height))
        for height in (534.99, 545.01, 1040.0):
            with self.subTest(height=height):
                self.assertFalse(getnative_module._is_banned_height(height))

        for height in (535.0, 540.0, 545.0, 2080.01, 2116.0):
            with self.subTest(source_height=2160, height=height):
                self.assertTrue(
                    getnative_module._is_banned_height(height, source_height=2160)
                )
        for height in (534.99, 545.01, 1070.0, 1080.0, 1090.0, 2080.0):
            with self.subTest(source_height=2160, height=height):
                self.assertFalse(
                    getnative_module._is_banned_height(height, source_height=2160)
                )

    def test_upstream_adjacent_drop_wins_over_smoothed_valley_floor(self) -> None:
        heights = [float(height) for height in range(875, 901)]
        errors = [0.00056 for _ in heights]
        errors[heights.index(887.0)] = 0.00052
        errors[heights.index(888.0)] = 0.00053
        errors[heights.index(889.0)] = 0.00048
        errors[heights.index(890.0)] = 0.00048
        errors[heights.index(891.0)] = 0.00051
        errors[heights.index(892.0)] = 0.00032
        errors[heights.index(893.0)] = 0.00064

        best_height, score, _, valid = getnative_module._best_height_from_curve(
            heights,
            errors,
        )

        self.assertEqual(best_height, 892.0)
        self.assertNotEqual(best_height, 887.0)
        self.assertGreater(score, 0.0)
        self.assertTrue(valid)


class GetnativeWorkflowTests(unittest.TestCase):
    @staticmethod
    def _result(height: float, score: float) -> dict:
        return {
            "height": height,
            "score": score,
            "range": [432, 1058],
            "kernel": "bicubic_0.333_0.333",
        }

    def test_height_ranking_caps_isolated_extreme_scores(self) -> None:
        results = [
            self._result(892, 2.0),
            self._result(892, 3.0),
            self._result(892, 20.0),
            self._result(945, 100.0),
            self._result(945, 50.0),
        ]

        kept = encode_and_audio_tasks._select_getnative_ranked_group(results)

        self.assertEqual([row["height"] for row in kept], [892, 892, 892])
        self.assertEqual(
            encode_and_audio_tasks._getnative_result_weight(self._result(892, 2.0)),
            encode_and_audio_tasks._getnative_result_weight(self._result(892, 200.0)),
        )

    def test_vpy_processing_values_patch_only_top_level_numeric_assignments(self) -> None:
        patch_value = vpy_edit_and_preview.VpyEditPreviewMixin._patch_vpy_processing_value_in_text
        values = {"denoise_strength": 0.0}

        self.assertEqual(
            patch_value("denoise_strength=6e-1  # keep", values),
            "denoise_strength=0  # keep",
        )
        self.assertEqual(
            patch_value("    denoise_strength = 0.6", values),
            "    denoise_strength = 0.6",
        )

    def test_customized_previous_vpy_is_not_partially_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vpy_path = Path(temp_dir) / "vpy.vpy"
            customized_helper = vpy_edit_and_preview._PREVIOUS_GETNATIVE_KERNEL_HELPER.replace(
                'raise ValueError(f"Unsupported getnative kernel: {kernel_name}")',
                'raise RuntimeError(f"Custom kernel: {kernel_name}")',
                1,
            )
            vpy_path.write_text(
                'native_kernel = ""  # optional, auto-generated by app\n\n'
                + customized_helper
                + vpy_edit_and_preview._PREVIOUS_GETNATIVE_DESCALE_BLOCK
                + vpy_edit_and_preview._LEGACY_VPY_FILTER_BLOCK,
                encoding="utf-8",
            )
            original = vpy_path.read_bytes()
            owner = SimpleNamespace(get_default_vpy_path=lambda: str(vpy_path))

            vpy_edit_and_preview.VpyEditPreviewMixin.ensure_default_vpy_file(owner)

            self.assertEqual(vpy_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
