import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

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

    def test_consensus_quit_honors_minimum_kernel_count(self) -> None:
        kernels = [f"kernel_{index}" for index in range(16)]
        coarse_calls: list[str] = []

        def fake_vpy_call(_input_png: str, params: dict) -> dict:
            if params["mode"] == "list_kernels":
                return {"kernels": kernels}
            if params.get("two_stage") and params.get("progress_phase") != "final":
                coarse_calls.append(params["kernel_name"])
            return {
                "heights": [718.0, 719.0, 720.0, 721.0, 722.0],
                "errors": [3.0, 2.0, 1.0, 2.0, 3.0],
                "evaluated_all": True,
            }

        with (
            patch.object(getnative_module, "_vpy_call", side_effect=fake_vpy_call),
            patch.object(
                getnative_module,
                "_best_height_from_curve",
                return_value=(720.0, 10.0, 1, True),
            ),
        ):
            getnative_module.getnative(
                "input.png",
                src_heights=range(500, 1001),
                fast_mode=True,
                min_kernels=8,
                max_kernels=16,
                consensus_quit=True,
            )

        self.assertEqual(len(coarse_calls), 8)

    def test_full_kernel_scan_batches_curves_into_one_vspipe_call(self) -> None:
        kernels = [f"kernel_{index}" for index in range(16)]
        modes: list[str] = []
        calls: list[dict] = []

        def fake_vpy_call(_input_png: str, params: dict) -> dict:
            calls.append(dict(params))
            modes.append(params["mode"])
            if params["mode"] == "collect_curves":
                return {
                    "curves": [
                        {
                            "kernel": kernel,
                            "heights": [718.0, 719.0, 720.0, 721.0, 722.0],
                            "errors": [3.0, 2.0, 1.0, 2.0, 3.0],
                            "evaluated_all": True,
                        }
                        for kernel in kernels
                    ]
                }
            if params["mode"] == "collect_curve":
                return {
                    "kernel": kernels[0],
                    "heights": [718.0, 719.0, 720.0, 721.0, 722.0],
                    "errors": [3.0, 2.0, 1.0, 2.0, 3.0],
                    "evaluated_all": True,
                }
            self.fail(f"unexpected VPy mode: {params['mode']}")

        with (
            patch.object(getnative_module, "_vpy_call", side_effect=fake_vpy_call),
            patch.object(
                getnative_module,
                "_best_height_from_curve",
                return_value=(720.0, 10.0, 1, True),
            ),
        ):
            result = getnative_module.getnative(
                "input.png",
                src_heights=range(500, 1001),
                fast_mode=True,
                score_quit=0.0,
                min_kernels=16,
                max_kernels=16,
                consensus_quit=False,
            )

        self.assertEqual(result["getnative_height"], 720.0)
        self.assertEqual(modes, ["collect_curves", "collect_curve"])
        self.assertTrue(calls[-1]["two_stage"])
        self.assertFalse(calls[-1]["coarse_half_size"])

    def test_540_interference_band_and_curve_tail_are_excluded(self) -> None:
        for height in (535.0, 540.0, 545.0, 1040.01, 1058.0):
            with self.subTest(height=height):
                self.assertTrue(getnative_module._is_banned_height(height))
        for height in (534.99, 545.01, 1040.0):
            with self.subTest(height=height):
                self.assertFalse(getnative_module._is_banned_height(height))

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

    def test_kernel_progress_message_includes_detection_result(self) -> None:
        with patch.object(getnative_module, "print_terminal_line") as emit:
            getnative_module._emit_getnative_progress(
                {
                    "phase": "kernel",
                    "index": 3,
                    "total": 16,
                    "image": "frame.png",
                    "kernel": "lanczos_3",
                    "height": 893.0,
                    "score": 12.5,
                    "curve_valid": True,
                    "skipped": True,
                }
            )

        message = emit.call_args.args[0]
        self.assertIn("3/16", message)
        self.assertIn("frame.png", message)
        self.assertIn("lanczos_3", message)
        self.assertIn("893.00p", message)
        self.assertIn("skipped=1", message)

    def test_parent_reads_each_external_progress_event_once(self) -> None:
        event = {
            "phase": "kernel",
            "index": 1,
            "total": 16,
            "image": "frame.png",
            "kernel": "bilinear",
            "height": 892.0,
            "score": 4.0,
            "curve_valid": True,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            progress_path = Path(temp_dir) / "progress.jsonl"
            progress_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            positions: dict[str, int] = {}
            paths = {"frame.png": str(progress_path)}

            first = encode_and_audio_tasks._read_getnative_progress_messages(paths, positions)
            second = encode_and_audio_tasks._read_getnative_progress_messages(paths, positions)

        self.assertEqual(len(first), 1)
        self.assertIn("frame.png", first[0])
        self.assertIn("892.00p", first[0])
        self.assertEqual(second, [])


class GetnativeWorkflowTests(unittest.TestCase):
    @staticmethod
    def _result(height: float, score: float) -> dict:
        return {
            "height": height,
            "score": score,
            "range": [432, 1058],
            "kernel": "bicubic_0.333_0.333",
        }

    def test_height_ranking_favors_high_resolution_and_score_without_consensus(self) -> None:
        results = [
            self._result(720, 5.0),
            self._result(721, 4.0),
            self._result(900, 100.0),
        ]

        kept = encode_and_audio_tasks._select_getnative_ranked_group(results)

        self.assertEqual([row["height"] for row in kept], [900])
        self.assertEqual(
            encode_and_audio_tasks._select_getnative_ranked_group([]),
            [],
        )

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

    def test_automatic_workflow_allows_twenty_parallel_samples(self) -> None:
        abundant_memory = 100 * 1024**3
        self.assertEqual(
            encode_and_audio_tasks.GETNATIVE_ESTIMATED_SAMPLE_MEMORY_BYTES,
            800 * 1024**2,
        )
        self.assertEqual(
            encode_and_audio_tasks._getnative_parallel_sample_count(64, abundant_memory),
            20,
        )
        self.assertEqual(
            encode_and_audio_tasks._getnative_parallel_sample_count(12, abundant_memory),
            12,
        )
        self.assertEqual(
            encode_and_audio_tasks._getnative_parallel_sample_count(64, 6 * 1024**3),
            5,
        )
        self.assertEqual(
            encode_and_audio_tasks._getnative_parallel_sample_count(0, abundant_memory),
            1,
        )

    def test_automatic_workflow_extracts_samples_incrementally(self) -> None:
        images = [f"frame_{index}.png" for index in range(8)]
        extraction_targets: list[int] = []
        events: list[str] = []

        def fake_extract(video_path: str, temp_dir: str, max_total: int = 100, **_kwargs) -> list[str]:
            del video_path, temp_dir
            extraction_targets.append(max_total)
            return images[:max_total]

        class ImmediateFuture:
            def __init__(self, image: str):
                self.image = image

            def result(self) -> dict:
                index = int(self.image.removeprefix("frame_").removesuffix(".png"))
                return {
                    "ok": True,
                    "image": self.image,
                    "height": 893.0,
                    "kernel": "bicubic_0.333_0.333",
                    "score": 10.0,
                    "range": [432, 1058],
                    "curve_valid": int(index in {0, 1, 4, 5, 6}),
                    "edge_hit": 0,
                    "decreasing_ratio": 0.5,
                }

        class ImmediateExecutor:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                events.append("executor_exit")
                return None

            def submit(self, _worker, image: str, _debug_dir, _progress_jsonl) -> ImmediateFuture:
                return ImmediateFuture(image)

        service = encode_and_audio_tasks.EncodeAudioTasksMixin()
        service.t = lambda text: text
        service._extract_sample_images = fake_extract
        with (
            patch.object(encode_and_audio_tasks, "_getnative_parallel_sample_count", return_value=4),
            patch.object(encode_and_audio_tasks, "ProcessPoolExecutor", ImmediateExecutor),
            patch.object(
                encode_and_audio_tasks,
                "wait",
                side_effect=lambda futures, **_kwargs: (set(futures), set()),
            ),
            patch.object(
                encode_and_audio_tasks,
                "_emit_encode_log_line",
                side_effect=lambda message: events.append(message),
            ),
        ):
            result = service._infer_native_resolution("video.m2ts")

        self.assertEqual(result["height"], 893)
        self.assertEqual(extraction_targets, [4, 8])
        first_sample_result = next(
            index for index, event in enumerate(events) if "getnative sample:" in event
        )
        self.assertLess(first_sample_result, events.index("executor_exit"))

    def test_worker_uses_permissive_curve_validity_and_preserves_debug_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "frame.png"
            debug_root = root / "debug"
            debug_root.mkdir()
            sentinel = debug_root / "keep.txt"
            sentinel.write_text("user data", encoding="utf-8")
            Image.new("RGB", (1920, 1080), color=(128, 128, 128)).save(image_path)
            detected = {
                "getnative_height": 720.0,
                "getnative_kernel": "bicubic_0.333_0.333",
                "getnative_score": 10.0,
                "getnative_curve_valid": 1,
                "getnative_curve_valid_strict": 0,
                "getnative_edge_hit": 0,
                "getnative_decreasing_ratio": 0.9,
            }

            with (
                patch.object(
                    encode_and_audio_tasks,
                    "auto_getnative",
                    return_value=detected,
                ) as mocked_getnative,
                patch.object(encode_and_audio_tasks, "KEEP_GETNATIVE_ARTIFACTS", False),
            ):
                result = encode_and_audio_tasks._estimate_native_from_image_worker(
                    str(image_path),
                    str(debug_root),
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["curve_valid"], 1)
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sorted(path.name for path in debug_root.iterdir()), ["keep.txt"])
            self.assertEqual(mocked_getnative.call_args.kwargs["min_kernels"], 16)
            self.assertEqual(mocked_getnative.call_args.kwargs["max_kernels"], 16)
            self.assertFalse(mocked_getnative.call_args.kwargs["consensus_quit"])

    def test_default_vpy_applies_every_detected_kernel_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vpy_path = Path(temp_dir) / "vpy.vpy"
            owner = SimpleNamespace(get_default_vpy_path=lambda: str(vpy_path))

            vpy_edit_and_preview.VpyEditPreviewMixin.ensure_default_vpy_file(owner)

            content = vpy_path.read_text(encoding="utf-8")
            ast.parse(content)
            self.assertIn('"bicubic_0.333_0.333": (1/3, 1/3)', content)
            self.assertIn('taps = int(taps_text)', content)
            self.assertIn('"spline64": "Despline64"', content)
            self.assertIn(
                'low = _descale_native(src16, native_w, nh, native_kernel)',
                content,
            )

    def test_existing_default_vpy_gets_the_exact_kernel_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vpy_path = Path(temp_dir) / "vpy.vpy"
            marker = 'native_kernel = ""  # optional, auto-generated by app\n\n'
            vpy_path.write_text(
                "custom_setting = 1\n"
                + marker
                + vpy_edit_and_preview._LEGACY_GETNATIVE_DESCALE_BLOCK,
                encoding="utf-8",
            )
            owner = SimpleNamespace(get_default_vpy_path=lambda: str(vpy_path))

            vpy_edit_and_preview.VpyEditPreviewMixin.ensure_default_vpy_file(owner)

            content = vpy_path.read_text(encoding="utf-8")
            self.assertIn("custom_setting = 1", content)
            self.assertIn(vpy_edit_and_preview._GETNATIVE_KERNEL_HELPER, content)
            self.assertIn(vpy_edit_and_preview._GETNATIVE_DESCALE_BLOCK, content)
            self.assertNotIn(vpy_edit_and_preview._LEGACY_GETNATIVE_DESCALE_BLOCK, content)

    def test_vpy_loader_converts_rgb_to_luma_without_lsmash_cache(self) -> None:
        source = Path(getnative_module.__file__).with_suffix(".vpy").read_text(encoding="utf-8")

        self.assertIn('matrix_s="709"', source)
        self.assertIn('LWLibavSource(path, cache=0)', source)
        self.assertIn('clip = clip.resize.Point(format=gray_fmt)', source)
        self.assertIn('abs(value - 540.0) <= 5.0 or value > 1040.0', source)
        self.assertIn('elif mode == "collect_curves":', source)
        self.assertIn('"phase": "kernel"', source)
        self.assertIn('BLURAYSUB_GETNATIVE_PROGRESS_JSONL', source)
        self.assertIn('early_stop_enabled = int(early_stop_patience) < len(src_heights)', source)
        self.assertIn('coarse_clip = core.std.CropAbs(', source)
        self.assertIn('scaled_h = float(h) * coarse_scale', source)
        self.assertIn('if completed_screens >= 3 else 0.0', source)
        self.assertIn('coarse_best_s < global_best_score * 0.45', source)


if __name__ == "__main__":
    unittest.main()
