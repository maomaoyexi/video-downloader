VERSION = "v1.9.5 WebUI"
VERSION_NUM = 10905

GITHUB_OWNER = "maomaoyexi"
GITHUB_REPO = "video-downloader"
EXE_NAME = "视频下载工具v1.9.5-GUI.exe"
UPDATE_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
MAX_UPDATE_SIZE = 512 * 1024 * 1024
IDLE_TIMEOUT = 30

DEFAULT_CONFIG = {
    "PLATFORM": "YouTube",
    "RESOLUTION": "best",
    "CODEC": "best",
    "AUDIO_QUALITY": "best",
    "OUTPUT_FORMAT": "mp4",
    "MERGE_MODE": 1,
    "AUDIO_SEP_MODE": 0,
    "THREADS": 4,
    "SPEED_LIMIT": 0,
    "PROXY_ENABLED": 0,
    "PROXY_TYPE": "http",
    "PROXY_ADDR": "127.0.0.1",
    "PROXY_PORT": "7890",
    "USE_COOKIES": 1,
    "COOKIE_MODE": 1,
    "BROWSER_NAME": "chrome",
    "BROWSER_PROFILE": "Default",
    "HWACCEL": "cpu",
    "EMBED_META": 1,
    "DOWNLOAD_THUMB": 1,
    "AUDIO_DOWNLOAD": 0,
    "WIN_FILENAMES": 1,
    "STRICT_FILENAME": 0,
    "NICO_COMMENTS": 0,
    "NICO_RECODE": 0,
    "ENABLE_LOG": 1,
    "MP3_BITRATE": 320,
    "DEL_WAV_AFTER_CONVERT": 0,
    "BILI_MULTIP_POLICY": "all",
}

RESOLUTION_OPTIONS = ["best", "2160", "1440", "1080", "720", "480", "360"]
RESOLUTION_LABELS = ["无限制", "4K (2160p)", "2K (1440p)", "1080P", "720P", "480P", "360P"]
CODEC_OPTIONS = ["best", "h264", "av1", "vp9"]
CODEC_LABELS = ["极致画质", "兼容优先(H.264)", "AV1优先", "VP9优先"]
AUDIO_OPTIONS = ["best", "192", "128"]
AUDIO_LABELS = ["最高音质", "均衡(192k)", "最小体积(128k)"]
FORMAT_OPTIONS = ["mp4", "mkv", "webm"]
AUDIO_SEP_OPTIONS = ["m4a", "mp3", "flac", "wav"]
AUDIO_SEP_LABELS = ["m4a(原生)", "MP3", "FLAC", "WAV"]
HWACCEL_OPTIONS = ["cpu", "h264_nvenc", "h264_qsv", "h264_amf"]
HWACCEL_LABELS = ["CPU软编码", "N卡 NVENC", "Intel QSV", "AMD AMF"]
BROWSER_OPTIONS = ["chrome", "edge", "firefox", "brave", "opera"]
PROXY_TYPE_OPTIONS = ["http", "socks5"]
MP3_BITRATE_OPTIONS = [128, 192, 256, 320]
BILI_POLICY_OPTIONS = ["all", "select"]

PLATFORM_INFO = [
    {"name": "YouTube", "color": "#FF0000", "domains": ["youtube.com", "youtu.be"]},
    {"name": "Bilibili", "color": "#FB7299", "domains": ["bilibili.com", "b23.tv"]},
    {"name": "Twitch", "color": "#9146FF", "domains": ["twitch.tv"]},
    {"name": "Niconico", "color": "#00A0D1", "domains": ["nicovideo.jp", "nico.ms"]},
    {"name": "Fantia", "color": "#E6399B", "domains": ["fantia.jp"]},
]
