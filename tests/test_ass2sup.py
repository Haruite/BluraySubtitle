import ctypes
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from src.domain.subtitles import ass2sup
from src.domain.subtitles.ass2sup import (
    BdnEvent,
    Crop,
    Segment,
    _build_event_packets,
    _build_graphics_payload,
    bdnxml_to_sup,
    merge_segments,
    parse_bdn_xml,
)


class AssToSupTests(unittest.TestCase):
    def test_rational_bdn_frame_rate_and_event_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            xml_path = Path(temporary_directory) / 'subtitle.xml'
            xml_path.write_text(
                '<BDN><Description><Format VideoFormat="1080p" FrameRate="30000/1001"/>'
                '</Description><Events><Event InTC="00:00:01:00" OutTC="00:00:02:00">'
                '<Graphic Width="2" Height="2" X="10" Y="20">subtitle.png</Graphic>'
                '</Event></Events></BDN>',
                encoding='utf-8',
            )
            document = parse_bdn_xml(str(xml_path))

        self.assertAlmostEqual(document.fps, 30000 / 1001)
        self.assertEqual((document.events[0].start_frame, document.events[0].end_frame), (30, 60))
        self.assertEqual((document.events[0].x, document.events[0].y), (10, 20))

    def test_identical_pixels_at_different_positions_remain_separate_events(self) -> None:
        crop_left = Crop(10, 20, 100, 30)
        crop_right = Crop(11, 20, 100, 30)
        segments = [[
            Segment(0, 10, crop_left, 'same-image'),
            Segment(10, 20, crop_right, 'same-image'),
        ]]
        events = merge_segments(segments)
        self.assertEqual(len(events), 2)
        self.assertEqual([event.crop.x for event in events], [10, 11])

    @unittest.skipUnless(ass2sup._native, 'ASS extension is unavailable')
    def test_native_compositor_matches_clipped_strided_masks(self) -> None:
        # The final bitmap row contains the mask width without stride padding.
        back_mask = (ctypes.c_uint8 * 13)(0, 32, 255, 128, 0, 0, 45, 100, 203, 0, 0, 255, 200)
        front_mask = (ctypes.c_uint8 * 8)(0, 20, 70, 0, 128, 255, 255, 0)
        front = ass2sup.ASS_Image(4, 2, 4, front_mask, 0xB0F02080, 0, 1, None, 0)
        back = ass2sup.ASS_Image(3, 3, 5, back_mask, 0x5522CC10, -1, 0, ctypes.pointer(front), 0)
        head = ctypes.pointer(back)
        with patch.object(ass2sup, '_native', None):
            expected = ass2sup._render_bitmap(head, 3, 3)
        self.assertEqual(ass2sup._render_bitmap(head, 3, 3), expected)

    @unittest.skipUnless(ass2sup._native, 'ASS extension is unavailable')
    def test_native_palette_and_rle_match_fallback(self) -> None:
        rgba = np.random.default_rng(23).integers(0, 256, (13, 17, 4), dtype=np.uint8)
        rgba[::2, ::2, 3] = 0
        image = Image.fromarray(rgba)
        row = np.repeat(np.array([0, 1, 2, 0, 5, 0, 6, 0], dtype=np.uint8),
                        [1, 2, 3, 63, 64, 0x3fff, 0x4000, 0x4000])
        stripes = np.stack([row, row[::-1]])[:, ::-1]
        actual, palette = ass2sup.image_to_indexed_and_palette(image)
        actual_rle = ass2sup.encode_rle(stripes)
        with patch.object(ass2sup, '_native', None):
            expected, expected_palette = ass2sup.image_to_indexed_and_palette(image)
            expected_rle = ass2sup.encode_rle(stripes)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(palette, expected_palette)
        self.assertEqual(actual_rle, expected_rle)

    def test_render_task_keeps_first_frame_when_libass_reports_no_change(self) -> None:
        mask = (ctypes.c_uint8 * 2)(255, 255)
        bitmap = ass2sup.ASS_Image(2, 1, 2, mask, 0xFFEEDD00, 0, 0, None, 0)
        head = ctypes.pointer(bitmap)

        def render(_renderer, _track, _timestamp, changed):
            ctypes.cast(changed, ctypes.POINTER(ctypes.c_int)).contents.value = 0
            return head

        with patch.multiple(ass2sup, G_LIB=SimpleNamespace(ass_render_frame=render),
                            G_WIDTH=2, G_HEIGHT=1, G_FPS_NUM=24, G_FPS_DEN=1, G_OUT_DIR=None):
            events = merge_segments([ass2sup.render_range((0, 3)), ass2sup.render_range((3, 6))])
        self.assertEqual([(event.start_frame, event.end_frame) for event in events], [(0, 6)])
        self.assertEqual(events[0].crop, Crop(0, 0, 2, 1))

    def test_every_fragment_uses_the_selected_object_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / 'large.png'
            pixels = np.indices((256, 512)).sum(axis=0).astype(np.uint8) % 2 + 1
            image = Image.fromarray(pixels, mode='P')
            palette = [0, 0, 0, 255, 255, 255, 255, 0, 0] + [0] * (768 - 9)
            image.putpalette(palette)
            image.info['transparency'] = bytes([0, 255, 255] + [255] * 253)
            image.save(image_path)
            event = BdnEvent(24, 48, False, 13, 721, str(image_path))
            graphics = _build_graphics_payload(event, 1920, 1080)
            self.assertEqual((graphics['x'], graphics['y']), (13, 721))
            packets, _, _, _ = _build_event_packets(
                event, graphics, 2, 1920, 1080, 24.0, 0x20, True, 7,
            )

        object_headers = []
        palette_headers = []
        offset = 0
        while offset < len(packets):
            self.assertEqual(packets[offset:offset + 2], b'PG')
            segment_type = packets[offset + 10]
            payload_size = struct.unpack_from('>H', packets, offset + 11)[0]
            payload = packets[offset + 13:offset + 13 + payload_size]
            if segment_type == 0x14:
                palette_headers.append(tuple(payload[:2]))
            elif segment_type == 0x15:
                object_headers.append(struct.unpack_from('>HB', payload))
            offset += 13 + payload_size
        self.assertGreater(len(object_headers), 1)
        self.assertEqual(object_headers, [(0, 7)] * len(object_headers))
        self.assertEqual(palette_headers, [(0, 7)])

    def test_compatibility_output_has_valid_packet_boundaries_and_fps_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image_path = root / 'subtitle.png'
            Image.new('RGBA', (16, 8), (255, 255, 255, 255)).save(image_path)
            xml_path = root / 'subtitle.xml'
            xml_path.write_text(
                '<BDN><Description><Format VideoFormat="1080p" FrameRate="30"/>'
                '</Description><Events><Event InTC="00:00:01:00" OutTC="00:00:02:00">'
                '<Graphic Width="16" Height="8" X="100" Y="900">subtitle.png</Graphic>'
                '</Event></Events></BDN>',
                encoding='utf-8',
            )
            output_path = root / 'subtitle.sup'
            self.assertEqual(bdnxml_to_sup(str(xml_path), str(output_path), 1, 'on'), 0)
            data = output_path.read_bytes()

        presentation_frame_rate_ids = []
        offset = 0
        while offset < len(data):
            self.assertEqual(data[offset:offset + 2], b'PG')
            segment_type = data[offset + 10]
            payload_size = struct.unpack_from('>H', data, offset + 11)[0]
            payload = data[offset + 13:offset + 13 + payload_size]
            self.assertEqual(len(payload), payload_size)
            if segment_type == 0x16:
                presentation_frame_rate_ids.append(payload[4])
            offset += 13 + payload_size
        self.assertEqual(offset, len(data))
        self.assertTrue(presentation_frame_rate_ids)
        self.assertEqual(set(presentation_frame_rate_ids), {0x50})


if __name__ == '__main__':
    unittest.main()
