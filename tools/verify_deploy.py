#!/usr/bin/env python3
"""树莓派部署验证脚本：API、播放器、缓存、TUI 全链路检查。"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from about import APP_AUTHOR, APP_NAME, APP_REPO, APP_VERSION  # noqa: E402

OK = "[OK]  "
FAIL = "[FAIL]"


def check(label, fn):
    try:
        result = fn()
        print(f"{OK} {label}: {result}")
        return True
    except Exception as e:
        print(f"{FAIL} {label}: {type(e).__name__}: {e}")
        return False


def main():
    print("=" * 60)
    print(f" {APP_NAME} v{APP_VERSION} 部署验证")
    print(f" 作者: {APP_AUTHOR}  {APP_REPO}")
    print("=" * 60)

    # 1. 依赖
    print("\n[1] 依赖检查")
    check("requests", lambda: __import__("requests").__version__)
    check("rich", lambda: __import__("rich").__file__.split("/")[-2])
    def _crypto_pkg():
        # apt 装的包叫 Cryptodome，pip 装的叫 Crypto，两种都要认
        import importlib.util
        for name in ("Crypto", "Cryptodome"):
            if importlib.util.find_spec(name):
                return name
        raise ImportError("未安装 pycryptodome")

    check("pycryptodome", _crypto_pkg)

    # 2. 模块导入（这里只关心能不能导入，不做实际调用）
    print("\n[2] 模块导入")
    from api.client import NeteaseAPI
    from api.crypto import weapi_encrypt
    from cache.db import CacheDB  # noqa: F401
    from player.mpv_wrapper import MpvPlayer  # noqa: F401
    print(f"{OK} 全部模块导入成功")

    def _enc_check():
        d = weapi_encrypt({"a": 1})
        return f"params={len(d['params'])} encSecKey={len(d['encSecKey'])}"

    check("weapi 加密", _enc_check)

    # 3. 网络 + API
    print("\n[3] 网络与 API")
    api = NeteaseAPI()
    check("music.163.com 可达", lambda: f"code={api.search('test', limit=1).get('code')}")

    songs = NeteaseAPI.extract_search_results(api.search("民谣", limit=5))
    check("搜索返回", lambda: f"{len(songs)} 首")
    for i, s in enumerate(songs, 1):
        print(f"      {i}. {s['name'][:20]:22s} {s['artist'][:12]:14s} fee={s['fee']}")

    if songs:
        info = NeteaseAPI.extract_song_url(api.song_url([songs[0]["id"]], "standard"))
        check("歌曲URL", lambda: f"可播放 br={info['br']}" if info["playable"] else info["reason"])

        ld = NeteaseAPI.extract_lyric(api.lyric(songs[0]["id"]))
        check("歌词", lambda: f"{len(ld['lyric'])} 字符")

        det = api.song_detail([songs[0]["id"]])
        norm = NeteaseAPI._normalize_song(det["songs"][0])
        check("歌曲详情", lambda: f"{norm['name']} - {norm['artist']}")

    # 4. 缓存
    print("\n[4] 本地缓存")
    db = CacheDB()
    db.cache_song({"id": 1, "name": "t", "artist": "a", "album": "b", "duration": 100})
    check("SQLite 读写", lambda: db.get_song(1)["name"])
    db.close()

    # 5. 播放器
    print("\n[5] mpv 播放器")
    player = MpvPlayer(volume=70)

    def test_mpv():
        player.start()
        v = player.get_volume()
        player.set_volume(50)
        v2 = player.get_volume()
        player.stop()
        return f"启动OK 音量 {v}->{v2} 关闭OK"

    check("mpv IPC", test_mpv)

    # 6. 实际播放测试
    if songs:
        print("\n[6] 实际播放测试 (3秒)")
        playable = None
        for s in songs:
            info = NeteaseAPI.extract_song_url(api.song_url([s["id"]], "standard"))
            if info["playable"]:
                playable = (s, info)
                break

        if playable:
            s, info = playable
            p = MpvPlayer(volume=50)
            try:
                p.start()
                p.load_file(info["url"])
                time.sleep(3)
                pos = p.get_position()
                dur = p.get_duration()
                title = p.get_title()
                print(f"     播放: {s['name']}")
                print(f"     位置: {pos:.1f}s / 时长: {dur:.1f}s")
                print(f"     mpv标题: {title[:40]}")
                if pos > 0.5:
                    print(f"{OK} 音频解码与播放正常")
                else:
                    print(f"{FAIL} 播放位置未推进，可能音频设备有问题")
            finally:
                p.stop()
        else:
            print("     跳过：无可用测试歌曲")

    print("\n" + "=" * 60)
    print(" 验证完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
