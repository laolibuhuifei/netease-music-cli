#!/usr/bin/env python3
"""低性能设备（树莓派 Zero 2W 等）上的网易云音乐命令行客户端。

用法：
    netease-music-cli              # 进入交互模式
    netease-music-cli login        # 扫码登录
    netease-music-cli search 晴天   # 搜索歌曲
    netease-music-cli play 186016  # 播放指定歌曲ID
    netease-music-cli playlist     # 查看歌单
    netease-music-cli recommend    # 每日推荐
    netease-music-cli diag         # 终端环境诊断（界面显示异常时用）
    netease-music-cli --version    # 查看版本与作者

环境变量：
    NETEASE_PLAIN=1   强制纯文本模式（终端不支持 ANSI 时）
"""

import os
import signal
import sys
import time

# 将项目目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from about import APP_AUTHOR, APP_NAME, APP_REPO, APP_VERSION, banner_lines
from api.client import NeteaseAPI
from auth.login import LoginManager
from cache.db import CacheDB
from cache.FileManager import FileManager
from config import ensure_dirs, load_config, save_config
from player.mpv_wrapper import MpvPlayer
from player.queue import PlayQueue
from ui.tui import TUI, format_duration

# 被认为是「无法渲染 ANSI」的 TERM 值
_DUMB_TERMS = {"", "dumb", "unknown", "cons25", "emacs"}


def build_console():
    """根据终端环境构造 Console。

    很多场景（串口控制台、某些 SSH 客户端、IDE 内置终端）会把 TERM
    上报成 dumb 或空。rich 对 dumb 终端有特殊处理：即使传
    force_terminal=True，它内部仍判定为 dumb 终端并拒绝渲染，
    结果就是「界面一片空白」。

    因此这里直接纠正 TERM，让 rich 按正常终端处理。

    Returns:
        (console, plain_mode)
        plain_mode=True 表示只能走纯文本模式（非交互输出）
    """
    term = os.environ.get("TERM", "").strip().lower()
    force_plain = os.environ.get("NETEASE_PLAIN", "").lower() in ("1", "true", "yes")
    is_tty = sys.stdout.isatty()

    # 用户显式要求纯文本
    if force_plain:
        return Console(no_color=True, highlight=False), True

    # 不是终端（被管道/重定向/ssh 未分配 tty）→ 只能纯文本
    if not is_tty:
        return Console(no_color=True, highlight=False), True

    # 是交互终端但 TERM 上报异常 → 直接纠正 TERM
    if term in _DUMB_TERMS:
        os.environ["TERM"] = "xterm-256color"
        os.environ.setdefault("COLORTERM", "truecolor")

    console = Console()
    # 有些 pty 会报告 0x0 的窗口尺寸（例如 pty.fork 新建的伪终端、
    # 或刚映射还没同步尺寸的终端窗口）。rich 遇到 0 宽/0 高会直接
    # 不输出任何内容，表现同样是「一片空白」。这里兜底成 80x24。
    try:
        size = console.size
    except Exception:
        size = None
    if size is None or size.width <= 0 or size.height <= 0:
        console = Console(width=80, height=24)

    return console, False


class App:
    """主应用控制器。"""

    def __init__(self):
        self.console, self.plain_mode = build_console()
        self.config = load_config()
        self.db = CacheDB()
        self.fm = FileManager()
        self.api = NeteaseAPI(
            music_u=self.config.get("music_u", ""),
            cookie=self.config.get("cookie", ""),
        )
        self.player = MpvPlayer(
            audio_device=self.config.get("audio_device", "auto"),
            volume=self.config.get("volume", 80),
        )
        self.queue = PlayQueue(mode=self.config.get("play_mode", "order"))
        self.tui = TUI(self.console, self.queue, self.api)
        self.running = False
        self.live = None

    # ---- 生命周期 ----

    def init(self):
        """初始化资源。"""
        ensure_dirs()
        self.player.start()
        self.player.set_volume(self.config.get("volume", 80))

    def cleanup(self):
        """清理资源。"""
        # 保存当前音量和播放模式
        self.config["volume"] = self.player.get_volume()
        self.config["play_mode"] = self.queue.mode
        save_config(self.config)

        self.player.stop()
        self.db.close()

    # ---- 播放控制 ----

    def play_song(self, song: dict) -> bool:
        """播放一首歌。

        Returns:
            True 表示成功加载播放，False 表示不可播放（无版权/VIP）
        """
        song_id = song["id"]

        # 获取歌曲 URL
        quality = self.config.get("quality", "standard")
        url_resp = self.api.song_url([song_id], level=quality)
        url_info = NeteaseAPI.extract_song_url(url_resp)

        if not url_info.get("playable"):
            reason = url_info.get("reason") or "无法获取播放地址"
            self.tui.set_message(f"跳过《{song.get('name', '')}》- {reason}")
            return False

        # 缓存歌曲信息
        self.db.cache_song(song)

        # 加载播放
        self.player.load_file(url_info["url"])
        self.tui.set_message(f"正在播放: {song.get('name', '')}")

        # 获取歌词
        self._fetch_lyric(song_id)
        return True

    def _fetch_lyric(self, song_id: int):
        """获取歌词（优先缓存）。"""
        # 先查缓存
        cached = self.db.get_lyric(song_id)
        if cached and cached.get("lyric"):
            self.tui.set_lyric(cached["lyric"])
            return

        # 从 API 获取
        lyric_resp = self.api.lyric(song_id)
        lyric_data = NeteaseAPI.extract_lyric(lyric_resp)

        if lyric_data.get("lyric"):
            self.db.cache_lyric(
                song_id,
                lyric_data["lyric"],
                lyric_data.get("translated", ""),
            )
            self.tui.set_lyric(lyric_data["lyric"])
        else:
            self.tui.set_lyric("")

    def play_next(self, auto_skip: int = 5):
        """播放下一首。

        Args:
            auto_skip: 遇到不可播放歌曲时最多连续跳过多少首，防止死循环
        """
        for _ in range(auto_skip):
            song = self.queue.next()
            if song is None:
                self.tui.set_message("播放队列已结束")
                return
            if self.play_song(song):
                return
            # 不可播放，继续尝试下一首
        self.tui.set_message("连续多首歌曲不可播放，请检查登录状态")

    def play_prev(self):
        """播放上一首。"""
        song = self.queue.prev()
        if song:
            self.play_song(song)

    # ---- 搜索 ----

    def do_search(self, keyword: str):
        """搜索歌曲。"""
        if not keyword:
            keyword = self._ask("搜索关键词（ESC 取消）: ")
            if not keyword:
                return

        self.tui.set_message(f"搜索中: {keyword}...")
        resp = self.api.search(keyword, limit=30)
        results = NeteaseAPI.extract_search_results(resp)

        if not results:
            self.tui.set_message("未找到结果")
            return

        # 缓存搜索结果
        self.db.add_search_history(keyword)
        self.db.cache_songs(results)

        self.tui.search_results = results
        self.tui.view = TUI.VIEW_SEARCH

    # ---- 歌单 ----

    def do_playlist(self):
        """查看歌单。"""
        self.tui.set_message("加载歌单...")
        resp = self.api.user_playlist()
        playlists = NeteaseAPI.extract_playlists(resp)

        if not playlists:
            self.tui.set_message("未找到歌单，请先登录")
            return

        self.tui.playlists = playlists
        self.tui.playlist_tracks = []
        self.tui.view = TUI.VIEW_PLAYLIST

    def open_playlist(self, index: int):
        """打开某个歌单的歌曲列表。"""
        if index < 0 or index >= len(self.tui.playlists):
            return

        playlist_id = self.tui.playlists[index]["id"]
        self.tui.set_message("加载歌单歌曲...")

        resp = self.api.playlist_detail(playlist_id)
        tracks = NeteaseAPI.extract_playlist_tracks(resp)

        if not tracks:
            self.tui.set_message("歌单为空")
            return

        self.db.cache_songs(tracks)
        self.tui.playlist_tracks = tracks

    # ---- 每日推荐 ----

    def do_recommend(self):
        """每日推荐。"""
        self.tui.set_message("加载每日推荐...")
        resp = self.api.recommend_songs()
        songs = NeteaseAPI.extract_recommend(resp)

        if not songs:
            self.tui.set_message("获取推荐失败，请先登录")
            return

        self.db.cache_songs(songs)
        self.tui.search_results = songs
        self.tui.view = TUI.VIEW_SEARCH

    # ---- 交互循环 ----

    def run_interactive(self):
        """交互模式主循环。

        使用 rich 的 Live（备用屏幕缓冲区）做原地重绘，
        并按内容签名做脏检查，避免整屏清屏导致的闪烁。
        """
        self.running = True

        # 检查登录状态（进入 Live 之前输出）
        if not self.config.get("music_u"):
            self.console.print("[yellow]未检测到登录信息，仅能播放免费歌曲[/yellow]")
            self.console.print("[dim]运行 netease-music-cli login 扫码登录可解锁全部歌曲[/dim]\n")
            time.sleep(1.2)

        # 注册信号处理
        def signal_handler(sig, frame):
            self.running = False
        signal.signal(signal.SIGINT, signal_handler)

        # 无法渲染 ANSI 时退回纯文本模式，避免「界面空白」
        if self.plain_mode:
            self._run_plain()
            return

        self.tui.enable_raw_input()

        last_sig = None
        try:
            with Live(
                self.tui.build(self.player),
                console=self.console,
                screen=True,              # 备用屏幕，无滚动残留
                auto_refresh=False,       # 手动控制刷新时机
                transient=False,
                vertical_overflow="visible",
            ) as live:
                self.live = live
                last_sig = self.tui.probe(self.player)
                live.refresh()

                while self.running:
                    key = self.tui.read_key(timeout=0.15)
                    if key:
                        self._handle_key(key)

                    # 检查播放结束事件
                    self._check_playback_events()

                    # 仅在内容真正变化时重绘（进度按秒变化 => 约 1 次/秒）
                    sig = self.tui.probe(self.player)
                    if sig != last_sig:
                        live.update(self.tui.build(self.player), refresh=True)
                        last_sig = sig

        except Exception as e:
            # Live 渲染失败（终端不支持备用屏幕等）→ 降级到纯文本
            self.console.print(f"\n[red]界面渲染失败，切换到纯文本模式: {e}[/red]")
            time.sleep(1)
            self._run_plain()

        finally:
            self.live = None
            self.tui.disable_raw_input()
            self.cleanup()

        # 退出备用屏幕后再打一行署名，不干扰界面
        self.console.print(
            f"[dim]{APP_NAME} v{APP_VERSION} · by {APP_AUTHOR} · {APP_REPO}[/dim]"
        )

    def _run_plain(self):
        """纯文本模式：不使用 Live / 备用屏幕，逐行输出状态。

        用于 TERM=dumb、输出被重定向、或终端不支持备用屏幕的场景。
        """
        # 非交互环境（如 ssh 未分配 tty、输出被管道）：给出提示后退出
        if not sys.stdin.isatty():
            self.console.print("[yellow]检测到当前不是交互终端，无法接收按键。[/yellow]")
            self.console.print("请用以下方式运行：")
            self.console.print("  ssh -t <用户名>@<设备地址> netease-music-cli    （强制分配 tty）")
            self.console.print("  netease-music-cli search 关键词                 （非交互命令）")
            cur = self.queue.current()
            if cur:
                self.console.print(f"当前歌曲: {cur['name']} - {cur['artist']}")
            return

        self.tui.enable_raw_input()
        self.console.print("[dim]纯文本模式（设置 TERM=xterm-256color 可获得完整界面）[/dim]")
        self.console.print("[dim]空格暂停  n下首  p上首  s搜索  q退出[/dim]\n")

        last_sig = None
        try:
            while self.running:
                key = self.tui.read_key(timeout=0.2)
                if key:
                    self._handle_key(key)

                self._check_playback_events()

                sig = self.tui.probe(self.player)
                if sig == last_sig:
                    continue
                last_sig = sig

                # 搜索/歌单等列表视图，简单打印
                if self.tui.view == TUI.VIEW_SEARCH and self.tui.search_results:
                    self.console.print("\n搜索结果：")
                    for i, s in enumerate(self.tui.search_results, 1):
                        self.console.print(
                            f"  {i:2d}. {s['name']} - {s['artist']}"
                        )
                    self.console.print("输入序号播放，s 重新搜索，ESC 返回")
                    continue

                if self.tui.view == TUI.VIEW_PLAYLIST and self.tui.playlists:
                    self.console.print("\n我的歌单：")
                    for i, p in enumerate(self.tui.playlists, 1):
                        self.console.print(f"  {i:2d}. {p['name']} ({p['track_count']}首)")
                    self.console.print("输入序号查看，ESC 返回")
                    continue

                cur = self.queue.current()
                if cur:
                    pos = self.player.get_position()
                    dur = self.player.get_duration() or cur.get("duration", 0) / 1000.0
                    state = "暂停" if self.player.is_paused() else "播放"
                    self.console.print(
                        f"[{state}] {cur['name']} - {cur['artist']}  "
                        f"{format_duration(pos)}/{format_duration(dur)}  "
                        f"Vol:{int(self.player.get_volume())}  "
                        f"[{self.queue.get_mode_label()}]"
                    )
                else:
                    self.console.print("[空闲] 按 s 搜索歌曲")

                msg = self.tui.get_message()
                if msg:
                    self.console.print(f"  {msg}")
        finally:
            self.tui.disable_raw_input()
            self.cleanup()

    def _ask(self, prompt_text: str) -> str:
        """在 Live 之外读取一行用户输入。

        临时退出备用屏幕，输入完成后恢复界面。
        支持 ESC 取消、退格、中文输入。
        """
        live = getattr(self, "live", None)
        if live is not None:
            live.stop()

        try:
            return self.tui.read_line(prompt_text)
        finally:
            if live is not None:
                live.start()
                live.update(self.tui.build(self.player), refresh=True)

    def _handle_key(self, key: str):
        """处理键盘输入。"""
        view = self.tui.view

        # 全局按键
        if key == "CTRL_C" or key == "CTRL_D":
            self.running = False
            return

        if key == "q" and view == TUI.VIEW_PLAYER:
            self.running = False
            return

        # 根据视图处理
        if view == TUI.VIEW_PLAYER:
            self._handle_player_key(key)
        elif view == TUI.VIEW_SEARCH:
            self._handle_search_key(key)
        elif view == TUI.VIEW_PLAYLIST:
            self._handle_playlist_key(key)
        elif view == TUI.VIEW_LYRIC:
            self._handle_lyric_key(key)
        elif view == TUI.VIEW_QUEUE:
            self._handle_queue_key(key)

    def _handle_player_key(self, key: str):
        """播放界面按键。"""
        if key == " ":  # 空格 - 暂停/播放
            self.player.toggle_pause()
        elif key == "n":  # 下一首
            self.play_next()
        elif key == "p":  # 上一首
            self.play_prev()
        elif key == "s":  # 搜索
            keyword = self._ask("搜索关键词（ESC 取消）: ")
            if keyword:
                self.do_search(keyword)
        elif key == "P":  # 歌单 (大写 P)
            self.do_playlist()
        elif key == "l":  # 歌词
            if self.tui.lyric_lines:
                self.tui.view = TUI.VIEW_LYRIC
            else:
                self.tui.set_message("暂无歌词")
        elif key == "r":  # 切换播放模式
            self.queue.cycle_mode()
            self.tui.set_message(f"播放模式: {self.queue.get_mode_label()}")
        elif key == "R":  # 每日推荐
            self.do_recommend()
        elif key == "Q":  # 查看完整队列
            self.tui.view = TUI.VIEW_QUEUE
        elif key == "UP":
            self.player.volume_up(5)
        elif key == "DOWN":
            self.player.volume_down(5)
        elif key == "LEFT":
            self.player.seek(-5)
        elif key == "RIGHT":
            self.player.seek(5)

    def _handle_search_key(self, key: str):
        """搜索界面按键。"""
        if key == "ESC":
            self.tui.view = TUI.VIEW_PLAYER
        elif key == "s":
            keyword = self._ask("搜索关键词（ESC 取消）: ")
            if keyword:
                self.do_search(keyword)
        elif key.isdigit():
            # 等待完整数字输入
            num_str = key
            next_key = self.tui.read_key(timeout=1.0)
            while next_key.isdigit():
                num_str += next_key
                next_key = self.tui.read_key(timeout=1.0)

            idx = int(num_str) - 1
            if 0 <= idx < len(self.tui.search_results):
                self.queue.replace(self.tui.search_results, start_index=idx)
                self.queue.current_index = idx - 1
                self.play_next()
                self.tui.view = TUI.VIEW_PLAYER
            else:
                self.tui.set_message("无效序号")

    def _handle_playlist_key(self, key: str):
        """歌单界面按键。"""
        if key == "ESC":
            if self.tui.playlist_tracks:
                self.tui.playlist_tracks = []
            else:
                self.tui.view = TUI.VIEW_PLAYER
        elif key.isdigit():
            num_str = key
            next_key = self.tui.read_key(timeout=1.0)
            while next_key.isdigit():
                num_str += next_key
                next_key = self.tui.read_key(timeout=1.0)

            idx = int(num_str) - 1

            if self.tui.playlist_tracks:
                # 歌单内歌曲 - 播放
                if 0 <= idx < len(self.tui.playlist_tracks):
                    songs = self.tui.playlist_tracks
                    self.queue.replace(songs, start_index=idx)
                    self.queue.current_index = idx - 1
                    self.play_next()
                    self.tui.view = TUI.VIEW_PLAYER
            else:
                # 歌单列表 - 打开
                self.open_playlist(idx)

    def _handle_lyric_key(self, key: str):
        """歌词界面按键。"""
        if key == "ESC":
            self.tui.view = TUI.VIEW_PLAYER

    def _handle_queue_key(self, key: str):
        """队列界面按键。"""
        if key == "ESC":
            self.tui.view = TUI.VIEW_PLAYER

    def _check_playback_events(self):
        """检查播放结束事件。"""
        events = self.player.poll_events()
        for event in events:
            if event.get("event") == "end-file":
                reason = event.get("reason", "")
                if reason == "eof":
                    # 正常播放结束，播下一首
                    self.play_next()

    # ---- 命令行模式 ----

    def cmd_diag(self):
        """打印终端环境诊断信息，用于排查界面显示问题。"""
        import platform

        print("=" * 52)
        print(f" {APP_NAME} v{APP_VERSION} 环境诊断")
        print(f" 作者: {APP_AUTHOR}  {APP_REPO}")
        print("=" * 52)
        print(f" TERM              : {os.environ.get('TERM')!r}")
        print(f" COLORTERM         : {os.environ.get('COLORTERM')!r}")
        print(f" stdout 是终端     : {sys.stdout.isatty()}")
        print(f" stdin  是终端     : {sys.stdin.isatty()}")
        print(f" 纯文本模式        : {self.plain_mode}")
        print(f" console.is_terminal: {self.console.is_terminal}")
        print(f" console.size      : {self.console.size}")
        print(f" Python            : {sys.version.split()[0]}")
        print(f" 平台              : {platform.platform()}")

        try:
            sz = os.get_terminal_size()
            print(f" 终端尺寸          : {sz.columns}x{sz.lines}")
        except OSError as e:
            print(f" 终端尺寸          : 获取失败 ({e})")

        print()
        print("--- 渲染测试 ---")
        try:
            self.console.print(
                Panel("如果你看到这个方框，说明 ANSI 渲染正常",
                      border_style="green")
            )
            print("  → 上方方框正常显示 = 终端支持 ANSI")
        except Exception as e:
            print(f"  → 渲染异常: {e}")

        print()
        print("--- 建议 ---")
        if os.environ.get("TERM", "") in _DUMB_TERMS:
            print(" TERM 异常，建议执行： export TERM=xterm-256color")
        if not sys.stdout.isatty():
            print(" 输出被重定向，无法显示交互界面")
        print(" 强制纯文本模式： NETEASE_PLAIN=1 netease-music-cli")

    def cmd_login(self):
        """登录命令。"""
        login_mgr = LoginManager(self.api)
        success = login_mgr.qrcode_login()
        if success:
            # 刷新 API 实例
            self.config = load_config()
            self.api = NeteaseAPI(
                music_u=self.config.get("music_u", ""),
                cookie=self.config.get("cookie", ""),
            )
            return True
        return False

    def cmd_search(self, keyword: str):
        """搜索并显示结果。"""
        resp = self.api.search(keyword, limit=30)
        results = NeteaseAPI.extract_search_results(resp)

        if not results:
            self.console.print("[red]未找到结果[/red]")
            return

        from rich.table import Table
        table = Table(title=f"搜索: {keyword}", show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("歌曲", style="white")
        table.add_column("歌手", style="cyan")
        table.add_column("专辑", style="dim")
        table.add_column("时长", style="dim", justify="right", width=8)

        for i, song in enumerate(results):
            table.add_row(
                str(i + 1),
                song.get("name", ""),
                song.get("artist", ""),
                song.get("album", ""),
                format_duration(song.get("duration", 0) / 1000),
            )

        self.console.print(table)

        # 询问是否播放
        print("\n输入序号播放，回车退出:")
        try:
            choice = input().strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    song = results[idx]
                    self.init()
                    self.queue.replace(results, start_index=idx)
                    self.queue.current_index = idx - 1
                    self.play_song(song)

                    # 简单等待播放
                    print(f"播放中: {song['name']} - {song['artist']}", flush=True)
                    print("按 Ctrl+C 退出", flush=True)
                    while True:
                        time.sleep(1)
                        events = self.player.poll_events()
                        for event in events:
                            if event.get("event") == "end-file":
                                self.play_next()
                                print(f"下一首: {self.queue.current()}")
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self.cleanup()

    def cmd_play(self, song_id: int):
        """直接播放歌曲ID。"""
        # 获取歌曲详情
        detail_resp = self.api.song_detail([song_id])
        if detail_resp.get("code") == 200:
            songs_data = detail_resp.get("songs", [])
            if songs_data:
                song = NeteaseAPI._normalize_song(songs_data[0])
                self.init()
                self.queue.add(song)
                self.queue.current_index = 0
                self.play_song(song)

                print(f"播放中: {song['name']} - {song['artist']}", flush=True)
                print("按 Ctrl+C 退出", flush=True)
                try:
                    while True:
                        time.sleep(1)
                        events = self.player.poll_events()
                        for event in events:
                            if event.get("event") == "end-file":
                                print("播放结束")
                                break
                except KeyboardInterrupt:
                    pass
                finally:
                    self.cleanup()
                return

        self.console.print(f"[red]无法获取歌曲信息: {song_id}[/red]")

    def cmd_playlist(self):
        """命令行查看歌单。"""
        resp = self.api.user_playlist()
        playlists = NeteaseAPI.extract_playlists(resp)

        if not playlists:
            self.console.print("[red]未找到歌单，请先登录[/red]")
            return

        from rich.table import Table
        table = Table(title="我的歌单", show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("歌单名", style="white")
        table.add_column("歌曲数", style="cyan", justify="right")
        table.add_column("创建者", style="dim")

        for i, pl in enumerate(playlists):
            table.add_row(
                str(i + 1),
                pl.get("name", ""),
                str(pl.get("track_count", 0)),
                pl.get("creator", ""),
            )

        self.console.print(table)

        print("\n输入序号查看歌曲，回车退出:")
        try:
            choice = input().strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(playlists):
                    pid = playlists[idx]["id"]
                    detail_resp = self.api.playlist_detail(pid)
                    tracks = NeteaseAPI.extract_playlist_tracks(detail_resp)

                    if tracks:
                        table2 = Table(title=playlists[idx]["name"], show_header=True, header_style="bold cyan")
                        table2.add_column("#", style="dim", width=4)
                        table2.add_column("歌曲", style="white")
                        table2.add_column("歌手", style="cyan")
                        table2.add_column("时长", style="dim", justify="right", width=8)

                        for i, song in enumerate(tracks):
                            table2.add_row(
                                str(i + 1),
                                song.get("name", ""),
                                song.get("artist", ""),
                                format_duration(song.get("duration", 0) / 1000),
                            )

                        self.console.print(table2)
        except (KeyboardInterrupt, EOFError):
            pass

    def cmd_recommend(self):
        """每日推荐。"""
        resp = self.api.recommend_songs()
        songs = NeteaseAPI.extract_recommend(resp)

        if not songs:
            self.console.print("[red]获取推荐失败，请先登录[/red]")
            return

        from rich.table import Table
        table = Table(title="每日推荐", show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("歌曲", style="white")
        table.add_column("歌手", style="cyan")
        table.add_column("时长", style="dim", justify="right", width=8)

        for i, song in enumerate(songs):
            table.add_row(
                str(i + 1),
                song.get("name", ""),
                song.get("artist", ""),
                format_duration(song.get("duration", 0) / 1000),
            )

        self.console.print(table)


def print_banner():
    """打印程序名、版本、作者、仓库地址。"""
    for line in banner_lines():
        print(line)


def print_help():
    """帮助信息 = 横幅 + 用法。"""
    print_banner()
    print()
    print(__doc__.split("用法：", 1)[1].strip())
    print()
    print(f"详细文档: {APP_REPO}#readme")


def main():
    """主入口。"""
    if len(sys.argv) < 2:
        # 交互模式
        app = App()
        app.init()
        app.run_interactive()
        return

    cmd = sys.argv[1]
    app = App()

    if cmd in ("-V", "--version", "version"):
        print_banner()
    elif cmd == "login":
        app.cmd_login()
    elif cmd == "search":
        if len(sys.argv) < 3:
            print(f"用法: {APP_NAME} search <关键词>")
            return
        app.cmd_search(" ".join(sys.argv[2:]))
    elif cmd == "play":
        if len(sys.argv) < 3:
            print(f"用法: {APP_NAME} play <歌曲ID>")
            return
        try:
            song_id = int(sys.argv[2])
        except ValueError:
            print("歌曲ID必须是数字")
            return
        app.cmd_play(song_id)
    elif cmd == "playlist":
        app.cmd_playlist()
    elif cmd == "recommend":
        app.cmd_recommend()
    elif cmd == "diag":
        app.cmd_diag()
    elif cmd in ("-h", "--help", "help"):
        print_help()
    else:
        print(f"未知命令: {cmd}")
        print()
        print_help()


if __name__ == "__main__":
    main()
