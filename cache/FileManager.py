"""歌词文件缓存管理。"""


from config import LYRIC_CACHE_DIR


class FileManager:
    """文件缓存管理（歌词等）。"""

    def __init__(self):
        LYRIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def save_lyric_file(self, song_id: int, lyric: str) -> str:
        """保存歌词到文件。

        Returns:
            文件路径
        """
        path = LYRIC_CACHE_DIR / f"{song_id}.lrc"
        with open(path, "w", encoding="utf-8") as f:
            f.write(lyric)
        return str(path)

    def load_lyric_file(self, song_id: int) -> str:
        """读取歌词文件。"""
        path = LYRIC_CACHE_DIR / f"{song_id}.lrc"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return f.read()
        return ""

    def lyric_file_exists(self, song_id: int) -> bool:
        return (LYRIC_CACHE_DIR / f"{song_id}.lrc").exists()

    def clear_all_lyrics(self):
        """清空歌词缓存。"""
        for f in LYRIC_CACHE_DIR.glob("*.lrc"):
            f.unlink()
