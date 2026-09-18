import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


YTDLP_AVAILABLE = importlib.util.find_spec("yt_dlp") is not None
PLUGIN_PATH = (
    Path(__file__).parents[1]
    / "dependency"
    / "yt-dlp-plugins"
    / "video_downloader"
    / "yt_dlp_plugins"
    / "postprocessor"
    / "twitcasting_parallel.py"
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class FakeDownloader:
    def __init__(self, responses):
        self.responses = responses
        self.params = {
            "concurrent_fragment_downloads": 2,
            "fragment_retries": 0,
            "ratelimit": None,
        }
        self.messages = []

    def urlopen(self, request):
        return FakeResponse(self.responses[request.url])

    def to_screen(self, message, *args, **kwargs):
        self.messages.append(message)

    def report_warning(self, message, *args, **kwargs):
        self.messages.append(message)


@unittest.skipUnless(YTDLP_AVAILABLE, "yt-dlp Python package is not installed")
class TwitCastingParallelPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("twitcasting_parallel_test", PLUGIN_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.plugin_class = module.TwitCastingParallelHlsPP

    def test_single_map_playlist_is_left_for_normal_downloader(self):
        plugin = self.plugin_class(FakeDownloader({}))
        playlist = """#EXTM3U
#EXT-X-MAP:URI="init.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-ENDLIST
"""
        self.assertIsNone(
            plugin._build_local_playlist("https://cdn.example/path/media.m3u8", playlist)
        )

    def test_multi_map_playlist_is_rewritten_to_local_assets(self):
        plugin = self.plugin_class(FakeDownloader({}))
        playlist = """#EXTM3U
#EXT-X-MAP:URI="init.0.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="init.1.mp4"
#EXTINF:2.0,
media.1.mp4
#EXT-X-ENDLIST
"""
        assets, rewritten, media_count, map_count = plugin._build_local_playlist(
            "https://cdn.example/path/media.m3u8", playlist
        )
        self.assertEqual(media_count, 2)
        self.assertEqual(map_count, 2)
        self.assertEqual(len(assets), 4)
        self.assertIn('URI="init-0001.mp4"', rewritten)
        self.assertIn('URI="init-0002.mp4"', rewritten)
        self.assertIn("media-000001.mp4", rewritten)
        self.assertIn("media-000002.mp4", rewritten)

    def test_prepare_downloads_assets_and_cleanup_removes_only_own_cache(self):
        manifest_url = "https://cdn.example/path/media.m3u8"
        playlist = b"""#EXTM3U
#EXT-X-MAP:URI="init.0.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="init.1.mp4"
#EXTINF:2.0,
media.1.mp4
#EXT-X-ENDLIST
"""
        responses = {
            manifest_url: playlist,
            "https://cdn.example/path/init.0.mp4": b"init-zero",
            "https://cdn.example/path/init.1.mp4": b"init-one",
            "https://cdn.example/path/media.0.mp4": b"media-zero",
            "https://cdn.example/path/media.1.mp4": b"media-one",
        }
        downloader = FakeDownloader(responses)
        plugin = self.plugin_class(downloader)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.mp4"
            info = {
                "id": "123",
                "_filename": str(output),
                "extractor_key": "TwitCasting",
            }
            format_info = {
                "url": manifest_url,
                "protocol": "m3u8_native",
                "format_id": "source",
                "vcodec": "h264",
                "acodec": "aac",
            }
            cache_dir = Path(plugin._prepare_format(info, format_info))

            self.assertTrue(cache_dir.is_dir())
            self.assertTrue((cache_dir / "local.m3u8").is_file())
            self.assertEqual(format_info["protocol"], "m3u8")
            self.assertTrue(format_info["url"].startswith("file:"))
            self.assertTrue(any("2 线程" in message for message in downloader.messages))

            # A refreshed signed manifest URL must reuse the completed fragments.
            refreshed_url = "https://refreshed.example/new-token/media.m3u8"
            resumed_plugin = self.plugin_class(FakeDownloader({refreshed_url: playlist}))
            resumed_format = {
                "url": refreshed_url,
                "protocol": "m3u8_native",
                "format_id": "source",
                "vcodec": "h264",
                "acodec": "aac",
            }
            resumed_cache = Path(resumed_plugin._prepare_format(info, resumed_format))
            self.assertEqual(resumed_cache, cache_dir)

            cleanup = self.plugin_class(downloader, cleanup="true")
            info["_tc_parallel_cache_dirs"] = [str(cache_dir)]
            cleanup._cleanup_cache(info)
            self.assertFalse(cache_dir.exists())


if __name__ == "__main__":
    unittest.main()
