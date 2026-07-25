import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from src.domain.subtitles.ass2sup import (
    BdnEvent,
    Crop,
    Segment,
    _build_event_packets,
    _build_graphics_payload,
    bdnxml_to_sup,
    fps_id_for,
    merge_segments,
    parse_bdn_xml,
)


class AssToSupTests(unittest.TestCase):
    def test_all_blu_ray_frame_rate_ids_are_distinct(self) -> None:
        expected = {
            24000 / 1001: 0x10,
            24.0: 0x20,
            25.0: 0x30,
            30000 / 1001: 0x40,
            30.0: 0x50,
            50.0: 0x60,
            60000 / 1001: 0x70,
            60.0: 0x80,
        }
        self.assertEqual({rate: fps_id_for(rate) for rate in expected}, expected)
        with self.assertRaisesRegex(ValueError, 'Unsupported Blu-ray frame rate'):
            fps_id_for(27.0)

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

    def test_every_fragment_uses_the_selected_object_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / 'large.png'
            pixels = np.indices((256, 512)).sum(axis=0).astype(np.uint8) % 2 + 1
            image = Image.fromarray(pixels, mode='P')
            palette = [0, 0, 0, 255, 255, 255, 255, 0, 0] + [0] * (768 - 9)
            image.putpalette(palette)
            image.info['transparency'] = bytes([0, 255, 255] + [255] * 253)
            image.save(image_path)
            event = BdnEvent(24, 48, False, 0, 0, str(image_path))
            graphics = _build_graphics_payload(event, 1920, 1080)
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
