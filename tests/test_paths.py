import os
import tempfile
import unittest
from pathlib import Path

from video_downloader.core.paths import AppPaths


class AppPathsTests(unittest.TestCase):
    def test_runtime_directories_use_clean_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(directory)
            paths.ensure_runtime_dirs()
            self.assertTrue(paths.dependency_dir.is_dir())
            self.assertTrue(paths.archive_dir.is_dir())
            self.assertTrue(paths.log_dir.is_dir())
            self.assertTrue((paths.download_dir / "YouTube").is_dir())
            self.assertTrue((paths.download_dir / "NicoChannel").is_dir())
            self.assertTrue((paths.download_dir / "Withny").is_dir())

    def test_canonical_dependency_wins_over_legacy_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = AppPaths(root)
            paths.dependency_dir.mkdir()
            canonical = paths.dependency_dir / "yt-dlp.exe"
            legacy = root / "yt-dlp.exe"
            canonical.touch()
            legacy.touch()
            self.assertEqual(paths.executable("yt-dlp", ".exe"), canonical)

    def test_legacy_dependency_is_used_when_canonical_copy_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "ffmpeg.exe"
            legacy.touch()
            self.assertEqual(AppPaths(root).executable("ffmpeg", ".exe"), legacy)

    def test_subprocess_path_starts_with_dependency_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(directory)
            env = paths.subprocess_env({"PATH": "existing"})
            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(paths.dependency_dir))
            self.assertTrue(env["PATH"].endswith("existing"))

    def test_runtime_setup_migrates_legacy_dependencies_and_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "yt-dlp.exe").write_bytes(b"legacy executable")
            legacy_video = root / "YouTube" / "creator" / "video.mp4"
            legacy_video.parent.mkdir(parents=True)
            legacy_video.write_bytes(b"video")

            paths = AppPaths(root)
            paths.ensure_runtime_dirs()

            self.assertFalse((root / "yt-dlp.exe").exists())
            self.assertEqual(
                (paths.dependency_dir / "yt-dlp.exe").read_bytes(),
                b"legacy executable",
            )
            self.assertFalse((root / "YouTube").exists())
            self.assertEqual(
                (paths.download_dir / "YouTube" / "creator" / "video.mp4").read_bytes(),
                b"video",
            )

    def test_runtime_setup_preserves_conflicting_legacy_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (dependency / "yt-dlp.exe").write_bytes(b"canonical")
            (root / "yt-dlp.exe").write_bytes(b"legacy")

            AppPaths(root).ensure_runtime_dirs()

            self.assertEqual((dependency / "yt-dlp.exe").read_bytes(), b"canonical")
            self.assertEqual(
                (dependency / "yt-dlp.exe.legacy-1").read_bytes(), b"legacy"
            )
            self.assertFalse((root / "yt-dlp.exe").exists())

    def test_runtime_setup_merges_both_legacy_archive_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            download = root / "download"
            download.mkdir()
            (root / "youtube_archive.txt").write_text(
                "youtube first\nyoutube shared\n", encoding="utf-8"
            )
            (download / "youtube_archive.txt").write_text(
                "youtube shared\nyoutube second\n", encoding="utf-8"
            )

            paths = AppPaths(root)
            paths.ensure_runtime_dirs()

            archive = paths.archive_dir / "youtube_archive.txt"
            self.assertEqual(
                archive.read_text(encoding="utf-8").splitlines(),
                ["youtube first", "youtube shared", "youtube second"],
            )
            self.assertFalse((root / "youtube_archive.txt").exists())
            self.assertFalse((download / "youtube_archive.txt").exists())

    def test_mixed_plugin_layout_returns_both_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (dependency / "nicochannel.zip").touch()
            (root / "yt-dlp-plugins").mkdir()

            self.assertEqual(
                AppPaths(root).plugin_dirs(),
                (dependency, root),
            )

    def test_archive_uses_legacy_file_only_when_canonical_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = AppPaths(root)
            paths.download_dir.mkdir()
            legacy = paths.download_dir / "youtube_archive.txt"
            legacy.touch()
            self.assertEqual(paths.archive("youtube_archive.txt"), legacy)

            paths.archive_dir.mkdir()
            canonical = paths.archive_dir / "youtube_archive.txt"
            canonical.touch()
            self.assertEqual(paths.archive("youtube_archive.txt"), canonical)


if __name__ == "__main__":
    unittest.main()
