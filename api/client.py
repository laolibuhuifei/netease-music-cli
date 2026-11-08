"""网易云 API 客户端封装。

接口：登录、搜索、歌单、歌曲URL、歌词、每日推荐。
"""

import json

import requests

from api.crypto import weapi_encrypt

# ---- 常量 ----
BASE_URL = "https://music.163.com"

# 请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com",
    "Content-Type": "application/x-www-form-urlencoded",
}

# weapi 请求路径前缀
WEAPI_PREFIX = "/weapi"


class NeteaseAPI:
    """网易云 API 客户端。"""

    def __init__(self, music_u: str = "", cookie: str = ""):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.music_u = music_u
        if music_u:
            self.session.cookies.set("MUSIC_U", music_u, domain=".music.163.com")
        if cookie:
            # 支持直接传完整 cookie 字符串
            for part in cookie.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    self.session.cookies.set(k.strip(), v.strip(), domain=".music.163.com")

    # ---- 内部请求方法 ----

    def _weapi_request(self, path: str, payload: dict) -> dict:
        """发送 weapi 加密请求。

        Args:
            path: 接口路径，如 "/song/url/v1"
            payload: 原始请求数据

        Returns:
            JSON 响应 dict
        """
        encrypted = weapi_encrypt(payload)
        url = f"{BASE_URL}{WEAPI_PREFIX}{path}"

        try:
            resp = self.session.post(
                url,
                data=encrypted,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            return {"code": -1, "msg": "请求超时"}
        except requests.exceptions.ConnectionError:
            return {"code": -2, "msg": "网络连接失败"}
        except Exception as e:
            return {"code": -3, "msg": f"请求异常: {e}"}

    # ---- 登录相关 ----

    def qrcode_create(self) -> dict:
        """生成登录二维码 key。

        Returns:
            {"code": 200, "unikey": "xxx"}
        """
        payload = {
            "type": 1,
            "noCheckToken": True,
        }
        return self._weapi_request("/login/qrcode/unikey", payload)

    def qrcode_check(self, key: str) -> dict:
        """检查二维码扫描状态。

        Returns:
            code: 800=过期, 801=等待扫码, 802=已扫码待确认, 803=已确认登录
        """
        payload = {
            "key": key,
            "type": 1,
        }
        return self._weapi_request("/login/qrcode/client/login", payload)

    def login_status(self) -> dict:
        """获取当前登录状态。"""
        return self._weapi_request("/w/nuser/account/get", {})

    def login_cellphone(self, phone: str, password: str = "", captcha: str = "") -> dict:
        """手机号登录。

        Args:
            phone: 手机号
            password: 明文密码（会先做MD5）
            captcha: 验证码（如果用验证码登录）
        """
        import hashlib
        payload = {
            "phone": phone,
            "rememberLogin": "true",
        }
        if password:
            payload["password"] = hashlib.md5(password.encode("utf-8")).hexdigest()
        if captcha:
            payload["captcha"] = captcha
        return self._weapi_request("/login/cellphone", payload)

    # ---- 搜索 ----

    def search(self, keywords: str, stype: int = 1, limit: int = 30, offset: int = 0) -> dict:
        """搜索歌曲。

        使用老版 /search/get/web 接口（匿名可用，无需登录）。
        注意：该接口返回字段为 artists/album/duration，与新版 ar/al/dt 不同。

        Args:
            keywords: 搜索关键词
            stype: 1=单曲, 10=专辑, 100=歌手, 1000=歌单, 1002=用户, 1006=歌词
            limit: 返回数量
            offset: 偏移

        Returns:
            搜索结果
        """
        payload = {
            "s": keywords,
            "type": stype,
            "limit": limit,
            "offset": offset,
            "total": True,
            "csrf_token": "",
        }
        return self._weapi_request("/search/get/web", payload)

    # ---- 歌曲 URL ----

    # 音质 -> 码率映射
    LEVEL_TO_BR = {
        "standard": 128000,
        "higher": 192000,
        "exhigh": 320000,
        "lossless": 999000,
        "hires": 1999000,
    }

    def song_url(self, song_ids: list, level: str = "standard") -> dict:
        """获取歌曲播放地址。

        使用 /song/enhance/player/url（weapi 版本，支持匿名获取免费歌曲）。

        Args:
            song_ids: 歌曲ID列表
            level: standard / higher / exhigh / lossless / hires

        Returns:
            {"code": 200, "data": [{"id":123, "url":"http://...", "br":128000,
                                    "code":200, "fee":8, ...}]}
            单曲不可播时该条 code 为 -110(需登录/VIP) 或 404(版权限制)，url 为 None
        """
        br = self.LEVEL_TO_BR.get(level, 128000)
        payload = {
            "ids": json.dumps(song_ids),
            "br": br,
        }
        return self._weapi_request("/song/enhance/player/url", payload)

    def song_detail(self, song_ids: list) -> dict:
        """获取歌曲详情（名称、歌手、专辑、封面等）。"""
        c = [{"id": sid, "v": 0} for sid in song_ids]
        payload = {
            "c": json.dumps(c),
        }
        return self._weapi_request("/v3/song/detail", payload)

    # ---- 歌词 ----

    def lyric(self, song_id: int) -> dict:
        """获取歌词。

        Returns:
            {"lrc": {"lyric": "..."}, "tlyric": {"lyric": "..."}, ...}
        """
        payload = {
            "id": song_id,
            "lv": -1,
            "tv": -1,
            "csrf_token": "",
        }
        return self._weapi_request("/song/lyric", payload)

    # ---- 歌单 ----

    def user_playlist(self, uid: int = 0, limit: int = 30, offset: int = 0) -> dict:
        """获取用户歌单列表。

        如果 uid=0，则使用当前登录用户。
        """
        if uid == 0:
            # 先获取当前用户 ID
            status = self.login_status()
            if status.get("code") == 200 and status.get("account"):
                uid = status["account"].get("id", 0)
            if uid == 0:
                return {"code": -1, "msg": "未登录"}

        payload = {
            "uid": uid,
            "limit": limit,
            "offset": offset,
            "includeVideo": True,
        }
        return self._weapi_request("/user/playlist", payload)

    def playlist_detail(self, playlist_id: int, limit: int = 100, offset: int = 0) -> dict:
        """获取歌单详情（包含歌曲列表）。"""
        payload = {
            "id": playlist_id,
            "n": limit,
            "s": 0,  # 不返回订阅者
        }
        return self._weapi_request("/v6/playlist/detail", payload)

    def playlist_track_ids(self, playlist_id: int, limit: int = 100, offset: int = 0) -> dict:
        """获取歌单所有歌曲ID。"""
        payload = {
            "id": playlist_id,
            "n": limit,
            "offset": offset,
        }
        return self._weapi_request("/v3/playlist/detail", payload)

    # ---- 每日推荐 ----

    def recommend_songs(self) -> dict:
        """每日推荐歌曲（需登录）。"""
        payload = {}
        return self._weapi_request("/v3/discovery/recommend/songs", payload)

    # ---- 私人 FM ----

    def personal_fm(self) -> dict:
        """私人 FM。"""
        payload = {}
        return self._weapi_request("/v1/radio/get", payload)

    # ---- 用户信息 ----

    def user_account(self) -> dict:
        """获取当前登录用户信息。"""
        return self._weapi_request("/w/nuser/account/get", {})

    # ---- 辅助方法 ----

    @staticmethod
    def _normalize_song(s: dict) -> dict:
        """把歌曲对象归一化为统一结构。

        兼容两种字段风格：
          - 新版 (song/detail, playlist/detail, recommend): ar / al / dt
          - 老版 (search/get):                            artists / album / duration
        """
        # 歌手
        artists = s.get("ar") or s.get("artists") or []
        artist = " / ".join(a.get("name", "") for a in artists if a.get("name"))

        # 专辑
        al = s.get("al") or s.get("album") or {}
        album = al.get("name", "") if isinstance(al, dict) else ""

        # 时长（毫秒）
        duration = s.get("dt") or s.get("duration") or 0

        # 封面
        cover = ""
        if isinstance(al, dict):
            cover = al.get("picUrl", "") or ""

        return {
            "id": s.get("id", 0),
            "name": s.get("name", ""),
            "artist": artist or "未知歌手",
            "album": album,
            "duration": duration,
            "cover": cover,
            "fee": s.get("fee", 0),  # 0=免费 1=VIP 4=购买专辑 8=免费低音质
        }

    @staticmethod
    def extract_search_results(resp: dict) -> list:
        """从搜索响应中提取歌曲列表。"""
        if resp.get("code") != 200:
            return []
        try:
            songs = (resp.get("result") or {}).get("songs") or []
            return [NeteaseAPI._normalize_song(s) for s in songs]
        except (KeyError, TypeError):
            return []

    @staticmethod
    def extract_song_url(resp: dict) -> dict:
        """从歌曲URL响应中提取第一首歌的URL信息。

        Returns:
            {"url": str, "br": int, "size": int, "code": int, "fee": int, "playable": bool}
            不可播放时 playable=False，code 为 -110(需登录/VIP) 或 404(版权限制)
        """
        if resp.get("code") != 200:
            return {"url": "", "playable": False, "code": resp.get("code", -1),
                    "reason": resp.get("msg", "请求失败")}
        data = resp.get("data") or []
        if not data:
            return {"url": "", "playable": False, "code": -1, "reason": "无数据"}

        item = data[0]
        url = item.get("url") or ""
        code = item.get("code", 0)
        fee = item.get("fee", 0)

        # 不可播放原因
        reason = ""
        if not url:
            if code == -110:
                reason = "需要登录或 VIP 会员"
            elif code == 404:
                reason = "版权限制，无法播放"
            else:
                reason = f"无法获取播放地址 (code={code})"

        return {
            "url": url,
            "br": item.get("br", 0),
            "size": item.get("size", 0),
            "type": item.get("type") or "",
            "code": code,
            "fee": fee,
            "playable": bool(url),
            "reason": reason,
        }

    @staticmethod
    def extract_lyric(resp: dict) -> dict:
        """从歌词响应中提取歌词文本。"""
        lrc = resp.get("lrc", {}).get("lyric", "")
        tlyric = resp.get("tlyric", {}).get("lyric", "")
        return {
            "lyric": lrc,
            "translated": tlyric,
        }

    @staticmethod
    def extract_playlists(resp: dict) -> list:
        """从歌单列表响应中提取歌单。"""
        if resp.get("code") != 200:
            return []
        try:
            playlists = resp.get("playlist", [])
            result = []
            for p in playlists:
                result.append({
                    "id": p["id"],
                    "name": p["name"],
                    "track_count": p.get("trackCount", 0),
                    "creator": p.get("creator", {}).get("nickname", ""),
                })
            return result
        except (KeyError, TypeError):
            return []

    @staticmethod
    def extract_playlist_tracks(resp: dict) -> list:
        """从歌单详情响应中提取歌曲列表。"""
        if resp.get("code") != 200:
            return []
        try:
            tracks = (resp.get("playlist") or {}).get("tracks") or []
            return [NeteaseAPI._normalize_song(s) for s in tracks]
        except (KeyError, TypeError):
            return []

    @staticmethod
    def extract_recommend(resp: dict) -> list:
        """从每日推荐响应中提取歌曲列表。"""
        if resp.get("code") != 200:
            return []
        try:
            songs = (resp.get("data") or {}).get("dailySongs") or []
            return [NeteaseAPI._normalize_song(s) for s in songs]
        except (KeyError, TypeError):
            return []
