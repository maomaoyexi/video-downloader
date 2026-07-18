"""
video_downloader.utils - 向后兼容 re-export shim。
实际实现已迁移到 video_downloader.core.platform。
"""

from video_downloader.core.platform import (  # noqa: F401
    asset_digest,
    clean_url,
    detect_platform,
    is_allowed_update_url,
    is_live_url,
    parse_version_tag,
    safe_decode,
    version_num_to_str,
)
