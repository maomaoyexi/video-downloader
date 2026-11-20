import json
import tempfile
import unittest
from pathlib import Path

from video_downloader.services.withny_archive import WithnyArchiveError, build_ffmpeg_command, load_and_select, redact_line


def entry(url, text="", mime="", status=200, cookies=None):
    return {
        "request": {"url": url, "cookies": cookies or []},
        "response": {"status": status, "content": {"mimeType": mime, "text": text}},
    }


class WithnyArchiveServiceTests(unittest.TestCase):
    def write_har(self, directory, entries):
        path = Path(directory) / "capture.har"
        path.write_text(json.dumps({"log": {"entries": entries}}), encoding="utf-8")
        return path

    def test_selects_valid_withny_hls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_har(directory, [
                entry("https://www.withny.fun/user/archives/7ee288a0-ed22-4930-bfd2-3a440517e784"),
                entry("https://media.example/master.m3u8?token=secret", "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nmedia.m3u8", "application/vnd.apple.mpegurl"),
                entry("https://media.example/media.m3u8?token=secret", "#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5\npart.ts", "application/vnd.apple.mpegurl"),
            ])
            selected, archive_url, duration, cookie_header = load_and_select(path)
            self.assertEqual(selected["type"], "master")
            self.assertNotIn("secret", selected["display_url"])
            self.assertIn("withny.fun/user/archives/", archive_url)
            self.assertEqual(duration, 5)
            self.assertEqual(cookie_header, "")

    def test_malformed_har_reports_a_readable_error(self):
        inputs = [
            [],
            {"log": []},
            {"log": {"entries": [None]}},
            {"log": {"entries": [{"request": [], "response": {}}]}},
            {"log": {"entries": [{"request": {"url": 123}, "response": {}}]}},
            {"log": {"entries": [{"request": {"headers": [None]}, "response": {}}]}},
            {"log": {"entries": [{"request": {}, "response": {"content": None}}]}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.har"
            for value in inputs:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaisesRegex(WithnyArchiveError, "HAR"):
                        load_and_select(path)

    def test_rejects_non_withny_and_encrypted_hls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_har(directory, [
                entry("https://example.com/archive/id"),
                entry("https://media.example/media.m3u8", "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\n#EXTINF:5\npart.ts"),
            ])
            with self.assertRaises(WithnyArchiveError):
                load_and_select(path)

    def test_redacts_signed_media_url(self):
        raw = "https://media.example/master.m3u8?token=unique-secret"
        self.assertNotIn("unique-secret", redact_line(f"failed {raw}", raw))

    def test_requires_and_extracts_cloudfront_signed_cookies(self):
        signed = [
            {"name": "CloudFront-Key-Pair-Id", "value": "key-id"},
            {"name": "CloudFront-Policy", "value": "policy"},
            {"name": "CloudFront-Signature", "value": "signature"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            entries = [
                entry("https://www.withny.fun/user/archives/7ee288a0-ed22-4930-bfd2-3a440517e784"),
                entry("https://archive.withny.fun/media/master.m3u8", "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nmedia.m3u8", cookies=signed),
                entry("https://archive.withny.fun/media/media.m3u8", "#EXTM3U\n#EXTINF:5\npart.ts", cookies=signed),
            ]
            path = self.write_har(directory, entries)
            _, _, _, cookie_header = load_and_select(path)
            self.assertIn("CloudFront-Signature=signature", cookie_header)
            entries[1]["request"]["cookies"] = []
            entries[2]["request"]["cookies"] = []
            path = self.write_har(directory, entries)
            with self.assertRaisesRegex(WithnyArchiveError, "CloudFront 签名 Cookie"):
                load_and_select(path)

    def test_ffmpeg_maps_only_best_video_and_audio(self):
        command, _ = build_ffmpeg_command("ffmpeg", "https://media.example/master.m3u8", "output.mp4")
        maps = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "-map"]
        self.assertEqual(maps, ["0:v:0", "0:a:0"])


if __name__ == "__main__":
    unittest.main()
