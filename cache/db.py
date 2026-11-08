"""SQLite 缓存：歌曲信息、歌词。

使用 SQLite 而非 JSON 文件，避免频繁 I/O 且支持高效查询。
数据库文件约几百 KB，对 microSD 友好。
"""

import sqlite3
import time

from config import CACHE_DIR

DB_PATH = CACHE_DIR / "cache.db"


class CacheDB:
    """缓存数据库。"""

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """建表。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY,
                name TEXT,
                artist TEXT,
                album TEXT,
                duration INTEGER,
                cached_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS lyrics (
                song_id INTEGER PRIMARY KEY,
                lyric TEXT,
                translated TEXT,
                cached_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT,
                searched_at INTEGER
            );
        """)
        self.conn.commit()

    # ---- 歌曲信息缓存 ----

    def cache_song(self, song: dict):
        """缓存歌曲信息。"""
        self.conn.execute(
            "INSERT OR REPLACE INTO songs (id, name, artist, album, duration, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                song["id"],
                song.get("name", ""),
                song.get("artist", ""),
                song.get("album", ""),
                song.get("duration", 0),
                int(time.time()),
            ),
        )
        self.conn.commit()

    def cache_songs(self, songs: list):
        """批量缓存歌曲信息。"""
        for song in songs:
            self.cache_song(song)

    def get_song(self, song_id: int) -> dict:
        """获取缓存的歌曲信息。"""
        row = self.conn.execute(
            "SELECT * FROM songs WHERE id = ?", (song_id,)
        ).fetchone()
        if row:
            return dict(row)
        return {}

    # ---- 歌词缓存 ----

    def cache_lyric(self, song_id: int, lyric: str, translated: str = ""):
        """缓存歌词。"""
        self.conn.execute(
            "INSERT OR REPLACE INTO lyrics (song_id, lyric, translated, cached_at) "
            "VALUES (?, ?, ?, ?)",
            (song_id, lyric, translated, int(time.time())),
        )
        self.conn.commit()

    def get_lyric(self, song_id: int) -> dict:
        """获取缓存的歌词。"""
        row = self.conn.execute(
            "SELECT * FROM lyrics WHERE song_id = ?", (song_id,)
        ).fetchone()
        if row:
            return {"lyric": row["lyric"], "translated": row["translated"]}
        return {}

    # ---- 搜索历史 ----

    def add_search_history(self, keyword: str):
        """记录搜索历史。"""
        self.conn.execute(
            "INSERT INTO search_history (keyword, searched_at) VALUES (?, ?)",
            (keyword, int(time.time())),
        )
        self.conn.commit()

    def get_search_history(self, limit: int = 10) -> list:
        """获取搜索历史。"""
        rows = self.conn.execute(
            "SELECT keyword FROM search_history ORDER BY searched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row["keyword"] for row in rows]

    # ---- 清理 ----

    def cleanup_old(self, days: int = 30):
        """清理超过指定天数的缓存。"""
        cutoff = int(time.time()) - days * 86400
        self.conn.execute("DELETE FROM search_history WHERE searched_at < ?", (cutoff,))
        self.conn.commit()

    def close(self):
        self.conn.close()
