"""Centralized application directory layout and legacy path compatibility."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


DOWNLOAD_PLATFORM_DIRS = (
    "YouTube",
    "Bilibili",
    "Twitch",
    "Niconico",
    "NicoChannel",
    "Fantia",
    "TwitCasting",
    "Twitter",
    "Withny",
)

# Runtime-only files that older portable releases placed beside the main
# executable.  Keep this list deliberately explicit: arbitrary user folders in
# the application directory must never be moved just because their names look
# dependency-related.
LEGACY_DEPENDENCY_ITEMS = (
    "yt-dlp.exe",
    "ffmpeg.exe",
    "ffprobe.exe",
    "deno.exe",
    "fantiadl.exe",
    "withny-dl-windows-amd64.exe",
    "nicochannel.zip",
    "yt-dlp-plugins",
    "bgutil-ytdlp-pot-provider",
    "node_modules",
    "package.json",
    "package-lock.json",
)

LEGACY_DOWNLOAD_DIRS = (*DOWNLOAD_PLATFORM_DIRS, "converted", "logs")


class AppPaths:
    """Resolve the clean runtime layout relative to the application directory.

    New installations keep third-party components in ``dependency`` and all
    generated downloads in ``download``.  Existing portable installations that
    still have a dependency in the application directory remain usable: an
    individual legacy asset is selected only when its canonical replacement is
    absent.
    """

    def __init__(self, app_dir: str | os.PathLike[str]):
        self.app_dir = Path(app_dir)
        self.dependency_dir = self.app_dir / "dependency"
        self.download_dir = self.app_dir / "download"
        self.archive_dir = self.download_dir / "archive"
        self.log_dir = self.download_dir / "logs"

    def ensure_runtime_dirs(self) -> None:
        """Create the clean layout and absorb files from older installations.

        Migration never overwrites an existing file.  A conflicting legacy
        file is retained in the destination with a ``.legacy-N`` suffix, so a
        partially migrated portable installation can be cleaned without data
        loss.
        """
        self.dependency_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_dependencies()
        self._migrate_legacy_download_dirs()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_archives()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for platform_name in DOWNLOAD_PLATFORM_DIRS:
            (self.download_dir / platform_name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _conflict_path(target: Path) -> Path:
        """Return a non-existing sibling name without changing the suffix."""
        index = 1
        while True:
            candidate = target.with_name(f"{target.name}.legacy-{index}")
            if not candidate.exists():
                return candidate
            index += 1

    @classmethod
    def _merge_path(cls, source: Path, target: Path) -> None:
        """Move *source* below *target*, recursively merging directories."""
        if not source.exists():
            return
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            return
        if source.is_dir() and target.is_dir():
            for child in tuple(source.iterdir()):
                cls._merge_path(child, target / child.name)
            try:
                source.rmdir()
            except OSError:
                pass
            return
        conflict = cls._conflict_path(target)
        conflict.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(conflict))

    def _migrate_legacy_dependencies(self) -> None:
        for name in LEGACY_DEPENDENCY_ITEMS:
            try:
                self._merge_path(self.app_dir / name, self.dependency_dir / name)
            except (OSError, shutil.Error):
                # A locked legacy executable must not prevent the application
                # from starting; dependency() still provides a fallback.
                continue

    def _migrate_legacy_download_dirs(self) -> None:
        for name in LEGACY_DOWNLOAD_DIRS:
            try:
                self._merge_path(self.app_dir / name, self.download_dir / name)
            except (OSError, shutil.Error):
                continue

    @staticmethod
    def _archive_lines(path: Path) -> list[str]:
        return [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line]

    def _merge_archive_file(self, source: Path, target: Path) -> None:
        if not target.exists():
            shutil.move(str(source), str(target))
            return
        try:
            combined = list(dict.fromkeys([
                *self._archive_lines(target),
                *self._archive_lines(source),
            ]))
        except (OSError, UnicodeError):
            self._merge_path(source, self._conflict_path(target))
            return

        descriptor, temp_name = tempfile.mkstemp(
            prefix=f"{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                if combined:
                    file.write("\n".join(combined) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, target)
            source.unlink()
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _migrate_legacy_archives(self) -> None:
        # Releases during the directory-layout transition wrote archives both
        # beside the executable and directly under download/.  Accept both.
        sources = [
            *self.app_dir.glob("*_archive.txt"),
            *self.download_dir.glob("*_archive.txt"),
        ]
        for source in sources:
            target = self.archive_dir / source.name
            if source != target:
                try:
                    self._merge_archive_file(source, target)
                except (OSError, shutil.Error):
                    continue

    def dependency(self, relative_path: str | os.PathLike[str]) -> Path:
        """Return a dependency path, falling back to the pre-v2.4 layout."""
        relative = Path(relative_path)
        canonical = self.dependency_dir / relative
        legacy = self.app_dir / relative
        if canonical.exists() or not legacy.exists():
            return canonical
        return legacy

    def executable(self, name: str, exe_suffix: str = "") -> Path:
        return self.dependency(f"{name}{exe_suffix}")

    def archive(self, filename: str) -> Path:
        """Return an archive path with fallback for a locked legacy file."""
        canonical = self.archive_dir / filename
        legacy_candidates = (
            self.download_dir / filename,
            self.app_dir / filename,
        )
        if canonical.exists() or not any(path.exists() for path in legacy_candidates):
            return canonical
        return next(path for path in legacy_candidates if path.exists())

    def plugin_dir(self) -> Path:
        """Return the root passed to yt-dlp for bundled plugin discovery."""
        return self.plugin_dirs()[0]

    def plugin_dirs(self) -> tuple[Path, ...]:
        """Return every plugin root required by a partially migrated install."""
        canonical_markers = (
            self.dependency_dir / "yt-dlp-plugins",
            self.dependency_dir / "nicochannel.zip",
        )
        legacy_markers = (
            self.app_dir / "yt-dlp-plugins",
            self.app_dir / "nicochannel.zip",
        )
        roots = []
        if any(path.exists() for path in canonical_markers):
            roots.append(self.dependency_dir)
        if any(path.exists() for path in legacy_markers):
            roots.append(self.app_dir)
        return tuple(roots or (self.dependency_dir,))

    def subprocess_env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """Return an environment that can discover co-located dependencies."""
        env = dict(os.environ if base is None else base)
        search_dirs = [str(self.dependency_dir)]
        # Keep the old portable layout working while users transition.
        if self.app_dir != self.dependency_dir:
            search_dirs.append(str(self.app_dir))
        current = env.get("PATH", "")
        if current:
            search_dirs.append(current)
        env["PATH"] = os.pathsep.join(search_dirs)
        return env
