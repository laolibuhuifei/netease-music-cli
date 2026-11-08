"""配置管理：cookie、音质、输出设备、缓存路径。"""

import json
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 配置文件路径
CONFIG_DIR = BASE_DIR / ".config"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 缓存目录
CACHE_DIR = BASE_DIR / ".cache"
COVER_CACHE_DIR = CACHE_DIR / "covers"
LYRIC_CACHE_DIR = CACHE_DIR / "lyrics"
SONG_CACHE_DIR = CACHE_DIR / "songs"

# mpv IPC socket
MPV_SOCKET = "/tmp/raspi-netease-mpv.sock"

# 网易云 API 基础地址
NETEASE_BASE_URL = "https://music.163.com"

# 默认音质: standard / higher / exhigh / lossless
# 树莓派 Zero 2W 推荐 standard(128k) 或 higher(192k)
DEFAULT_QUALITY = "standard"

# 默认音频设备 (mpv 设备名)
# 注意：mpv 不接受 "default"，合法值如 auto / alsa / alsa/sysdefault /
#       alsa/hdmi:CARD=vc4hdmi / pipewire / pulse
# auto 最省心，会自行选择可用输出
DEFAULT_AUDIO_DEVICE = "auto"

# 默认配置
DEFAULT_CONFIG = {
    "cookie": "",
    "music_u": "",
    "quality": DEFAULT_QUALITY,
    "audio_device": DEFAULT_AUDIO_DEVICE,
    "volume": 80,
    "play_mode": "order",  # order / repeat-one / random
    "cache_lyrics": True,
    "cache_covers": False,  # 封面缓存，树莓派存储紧张可关
}


def ensure_dirs():
    """确保所有必要目录存在。"""
    for d in [CONFIG_DIR, CACHE_DIR, COVER_CACHE_DIR, LYRIC_CACHE_DIR, SONG_CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """加载配置，不存在则返回默认配置。"""
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            # 合并默认值，防止新字段缺失
            merged = {**DEFAULT_CONFIG, **cfg}
            return merged
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """保存配置到文件。"""
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def update_config(key: str, value):
    """更新单个配置项。"""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
    return cfg
