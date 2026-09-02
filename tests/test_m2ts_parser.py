import os
import tempfile
import unittest

from src.bdmv import MPLS
from src.bdmv.m2ts import M2TS


class M2TSParserTest(unittest.TestCase):
    @staticmethod
    def _transport_packet(
        pid: int, payload: bytes, *, payload_unit_start: bool = False, m2ts: bool = True, pcr: int | None = None
    ) -> bytes:
        header = bytes([
            0x47, ((pid >> 8) & 0x1F) | (0x40 if payload_unit_start else 0), pid & 0xFF,
            0x30 if pcr is not None else 0x10,
        ])
        adaptation = b''
        if pcr is not None:
            adaptation = bytes([
                7, 0x10, (pcr >> 25) & 0xFF, (pcr >> 17) & 0xFF, (pcr >> 9) & 0xFF,
                (pcr >> 1) & 0xFF, ((pcr & 1) << 7) | 0x7E, 0,
            ])
        packet = header + adaptation + payload
        if len(packet) > 188:
            raise ValueError('Synthetic TS payload is too large')
        packet += b'\xff' * (188 - len(packet))
        return (b'\x00' * 4 + packet) if m2ts else packet

    @staticmethod
    def _pes(video_payload: bytes, pts: int) -> bytes:
        pts_bytes = bytes([
            0x21 | (((pts >> 30) & 0x07) << 1),
            (pts >> 22) & 0xFF,
            0x01 | (((pts >> 15) & 0x7F) << 1),
            (pts >> 7) & 0xFF,
            0x01 | ((pts & 0x7F) << 1),
        ])
        return b'\x00\x00\x01\xe0\x00\x00\x80\x80\x05' + pts_bytes + video_payload

    def _write_stream(self, *, m2ts: bool = True) -> str:
        pat = bytes.fromhex('00b00d0001c100000001e10000000000')
        pmt = bytes.fromhex('02b0120001c10000f011f00024f011f00000000000')
        # Real HEVC VPS bytes from a UHD Blu-ray. Its timing fields are 24000/1001.
        vps = bytes.fromhex('40010c01ffff222000000300b00000030000030099148c0c00000fa4000177014000')
        data = b''.join([
            self._transport_packet(0x0000, b'\x00' + pat, payload_unit_start=True, m2ts=m2ts),
            self._transport_packet(0x0100, b'\x00' + pmt, payload_unit_start=True, m2ts=m2ts),
            self._transport_packet(0x1011, self._pes(b'\x00\x00\x01' + vps, 90_000), payload_unit_start=True, m2ts=m2ts, pcr=90_000),
            self._transport_packet(0x1011, self._pes(b'\x00\x00\x01' + vps, 180_000), payload_unit_start=True, m2ts=m2ts, pcr=180_000),
        ])
        handle, path = tempfile.mkstemp(suffix='.m2ts' if m2ts else '.ts')
        os.close(handle)
        with open(path, 'wb') as stream:
            stream.write(data)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_m2ts_tracks_timestamps_frame_rate_and_frame_count(self) -> None:
        parser = M2TS(self._write_stream())
        tracks = parser.get_tracks_info()
        self.assertEqual([(track['pid'], track['codec_type'], track['codec_name']) for track in tracks], [(0x1011, 'video', 'hevc')])
        self.assertEqual(parser.get_first_pts(), 90_000)
        self.assertEqual(parser.get_last_pts(), 180_000)
        self.assertEqual(parser.get_duration(prefer_pcr=False), 90_000)
        self.assertAlmostEqual(parser.read_frame_rate_from_m2ts(), 23.976, places=3)
        self.assertEqual(parser.get_total_frames(), 24)

    def test_plain_ts_layout_uses_the_same_parser(self) -> None:
        parser = M2TS(self._write_stream(m2ts=False))
        self.assertEqual(parser.get_tracks_info(m2ts=False)[0]['pid'], 0x1011)
        self.assertAlmostEqual(parser.read_frame_rate_from_m2ts(m2ts=False), 23.976, places=3)

    def test_pts_scan_does_not_mutate_skipped_pid_set(self) -> None:
        skipped = {0x1200}
        M2TS(self._write_stream()).get_first_pts(skip_pids=skipped)
        self.assertEqual(skipped, {0x1200})

    def test_mpls_tracks_come_directly_from_the_first_play_item_stn(self) -> None:
        def pair(pid: int, stream_type: int, language: str = '') -> dict[str, object]:
            attributes: dict[str, object] = {'StreamCodingType': stream_type}
            if language:
                attributes['LanguageCode'] = language
            return {
                'StreamEntry': {'RefToStreamPID': pid},
                'StreamAttributes': attributes,
            }

        parser = MPLS()
        parser.data = {'PlayList': {'PlayItems': [{'STNTable': {
            'PrimaryVideoStreamEntries': [pair(0x1011, 0x24)],
            'PrimaryAudioStreamEntries': [pair(0x1100, 0x83, 'eng')],
            'PrimaryPGStreamEntries': [pair(0x12A2, 0x90, 'jpn')],
            'DVStreamEntries': [pair(0x1015, 0x24)],
        }}]}}

        self.assertEqual(
            [
                (track['pid'], track['codec_type'], track['codec_name'], track['language'])
                for track in parser.get_tracks_info()
            ],
            [
                (0x1011, 'video', 'hevc', 'und'),
                (0x1015, 'video', 'hevc', 'und'),
                (0x1100, 'audio', 'truehd', 'eng'),
                (0x12A2, 'subtitle', 'pgs', 'jpn'),
            ],
        )


if __name__ == '__main__':
    unittest.main()
