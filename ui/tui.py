"""TUI 交互界面。

渲染采用 rich 的 Live + 备用屏幕缓冲区（alternate screen），
配合「内容签名」做脏检查：只有界面内容真正变化时才重绘。
进度条按秒变化，因此实际重绘频率约 1 次/秒，不会闪烁。
"""

import os
import select
import sys
import termios
import time
import tty

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from about import APP_NAME
from api.client import NeteaseAPI
from player.queue import PlayQueue


def format_duration(seconds: int) -> str:
    """格式化时长为 mm:ss。"""
    if seconds <= 0:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def make_progress_bar(current: float, total: float, width: int = 25) -> str:
    """生成纯文本进度条。"""
    if total <= 0:
        return "░" * width
    filled = int(width * current / total)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


class TUI:
    """终端交互界面。"""

    # 界面模式
    VIEW_PLAYER = "player"
    VIEW_SEARCH = "search"
    VIEW_PLAYLIST = "playlist"
    VIEW_LYRIC = "lyric"
    VIEW_QUEUE = "queue"

    def __init__(self, console: Console, queue: PlayQueue, api: NeteaseAPI):
        self.console = console
        self.queue = queue
        self.api = api
        self.view = self.VIEW_PLAYER
        self.lyric_lines: list = []      # 当前歌词
        self.lyric_times: list = []      # 歌词时间戳
        self.search_results: list = []
        self.playlists: list = []
        self.playlist_tracks: list = []
        self.message: str = ""
        self.message_time = 0
        self._old_termios = None
        self._raw = False

    # ---- 键盘输入 ----

    def enable_raw_input(self):
        """启用 raw 模式，逐字符读取键盘输入。

        注意：不使用 tty.setraw()，因为它内部用 TCSAFLUSH，
        会丢弃缓冲区中已到达的按键。这里用 TCSADRAIN 手动设置。

        stdin 不是终端时（如 ssh 未分配 tty）静默跳过，不抛异常。
        """
        self._raw = False
        try:
            fd = sys.stdin.fileno()
            if not os.isatty(fd):
                return
            if self._old_termios is None:
                self._old_termios = termios.tcgetattr(fd)
        except (OSError, ValueError, termios.error):
            return

        try:
            mode = termios.tcgetattr(fd)
            # 输入标志：关闭各种转换与流控
            mode[tty.IFLAG] &= ~(
                termios.IGNBRK | termios.BRKINT | termios.PARMRK
                | termios.ISTRIP | termios.INLCR | termios.IGNCR
                | termios.ICRNL | termios.IXON
            )
            # 输出标志：必须保留 OPOST + ONLCR。
            # 关掉 OPOST 后 \n 不再被翻译成回车换行，rich 输出的每一行都会
            # 从上一行结尾的列继续写，整屏"楼梯式"错位并滚出可视区，
            # 表现就是启动后一片全黑（但程序其实已经正常渲染了）。
            mode[tty.OFLAG] |= termios.OPOST | termios.ONLCR
            # 控制标志：8 位字符
            mode[tty.CFLAG] &= ~(termios.CSIZE | termios.PARENB)
            mode[tty.CFLAG] |= termios.CS8
            # 本地标志：关闭回显、规范模式、信号
            mode[tty.LFLAG] &= ~(
                termios.ECHO | termios.ECHONL | termios.ICANON
                | termios.ISIG | termios.IEXTEN
            )
            mode[tty.CC][termios.VMIN] = 1
            mode[tty.CC][termios.VTIME] = 0

            termios.tcsetattr(fd, termios.TCSADRAIN, mode)
            self._raw = True
        except (OSError, ValueError, termios.error):
            self._raw = False

    def disable_raw_input(self):
        """恢复终端原始设置。"""
        if not self._old_termios:
            return
        try:
            fd = sys.stdin.fileno()
            termios.tcsetattr(fd, termios.TCSADRAIN, self._old_termios)
        except (OSError, ValueError, termios.error):
            pass
        self._raw = False

    def read_key(self, timeout: float = 0.1) -> str:
        """读取一个按键（非阻塞）。

        返回空字符串表示无输入或当前不可交互。
        """
        if not self._raw:
            time.sleep(timeout)
            return ""

        fd = sys.stdin.fileno()
        rlist, _, _ = select.select([fd], [], [], timeout)
        if not rlist:
            return ""

        ch = os.read(fd, 1).decode("utf-8", errors="ignore")

        # 处理转义序列
        if ch == "\x1b":
            rlist, _, _ = select.select([fd], [], [], 0.05)
            if rlist:
                ch2 = os.read(fd, 1).decode("utf-8", errors="ignore")
                if ch2 == "[":
                    rlist, _, _ = select.select([fd], [], [], 0.05)
                    if rlist:
                        ch3 = os.read(fd, 1).decode("utf-8", errors="ignore")
                        if ch3 == "A":
                            return "UP"
                        elif ch3 == "B":
                            return "DOWN"
                        elif ch3 == "C":
                            return "RIGHT"
                        elif ch3 == "D":
                            return "LEFT"
                        return f"ESC[{ch3}"
                    return "ESC["
                return "ESC"
            return "ESC"

        # Ctrl+C
        if ch == "\x03":
            return "CTRL_C"
        # Ctrl+D
        if ch == "\x04":
            return "CTRL_D"

        return ch

    def _read_utf8_char(self, timeout: float = 0.5) -> str:
        """读取一个完整 UTF-8 字符（支持中文输入）。"""
        fd = sys.stdin.fileno()
        rlist, _, _ = select.select([fd], [], [], timeout)
        if not rlist:
            return ""

        raw = os.read(fd, 1)
        if not raw:
            return ""

        first = raw[0]
        extra = 0
        if first >= 0xF0:
            extra = 3
        elif first >= 0xE0:
            extra = 2
        elif first >= 0xC0:
            extra = 1

        for _ in range(extra):
            rlist, _, _ = select.select([fd], [], [], 0.05)
            if not rlist:
                break
            raw += os.read(fd, 1)

        return raw.decode("utf-8", errors="ignore")

    def read_line(self, prompt_text: str, timeout: float = 60) -> str:
        """在 raw 模式下读取一行输入。

        支持：退格删除、ESC 取消、中文输入。
        返回空字符串表示取消或超时。
        """
        sys.stdout.write(prompt_text)
        sys.stdout.flush()

        chars: list = []
        deadline = time.time() + timeout

        while time.time() < deadline:
            ch = self._read_utf8_char(0.5)
            if not ch:
                continue

            # 回车确认
            if ch in ("\r", "\n"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return "".join(chars).strip()

            # ESC 取消
            if ch == "\x1b":
                sys.stdout.write("  (已取消)\r\n")
                sys.stdout.flush()
                return ""

            # Ctrl+C 取消
            if ch == "\x03":
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return ""

            # 退格
            if ch in ("\x7f", "\b"):
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue

            # 忽略其他控制字符
            if ord(ch[0]) < 32:
                continue

            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()

        sys.stdout.write("\r\n")
        sys.stdout.flush()
        return "".join(chars).strip()

    # ---- 消息 ----

    def set_message(self, msg: str):
        self.message = msg
        self.message_time = time.time()

    def get_message(self) -> str:
        if time.time() - self.message_time > 3:
            return ""
        return self.message

    # ---- 内容签名（脏检查）----

    def probe(self, player) -> tuple:
        """采集当前界面的关键状态，用于判断是否需要重绘。

        只做轻量属性读取，不构造渲染对象。
        """
        msg = self.get_message()

        if self.view == self.VIEW_PLAYER:
            cur = self.queue.current()
            return (
                self.VIEW_PLAYER,
                cur.get("id") if cur else 0,
                cur.get("name") if cur else "",
                int(player.is_paused()),
                int(player.get_position()),      # 按秒取整，避免每帧变化
                int(player.get_volume()),
                self.queue.mode,
                len(self.queue),
                self.queue.current_index,
                msg,
            )

        if self.view == self.VIEW_SEARCH:
            return (self.VIEW_SEARCH, len(self.search_results), msg)

        if self.view == self.VIEW_PLAYLIST:
            return (
                self.VIEW_PLAYLIST,
                len(self.playlists),
                len(self.playlist_tracks),
                msg,
            )

        if self.view == self.VIEW_LYRIC:
            return (
                self.VIEW_LYRIC,
                self._current_lyric_index(player.get_position()),
                len(self.lyric_lines),
                msg,
            )

        if self.view == self.VIEW_QUEUE:
            return (self.VIEW_QUEUE, len(self.queue), self.queue.current_index, msg)

        return (self.view, msg)

    def _current_lyric_index(self, pos: float) -> int:
        """根据播放位置找到当前歌词行号。"""
        idx = 0
        for i, t in enumerate(self.lyric_times):
            if pos >= t:
                idx = i
            else:
                break
        return idx

    # ---- 构建渲染对象 ----

    def build(self, player):
        """构建当前界面的渲染对象。"""
        if self.view == self.VIEW_SEARCH:
            return self._build_search_view()
        if self.view == self.VIEW_PLAYLIST:
            return self._build_playlist_view()
        if self.view == self.VIEW_LYRIC:
            return self._build_lyric_view(player)
        if self.view == self.VIEW_QUEUE:
            return self._build_queue_view()
        return self._build_player_view(player)

    def _message_line(self):
        """临时消息行。"""
        msg = self.get_message()
        if not msg:
            return None
        return Align.center(Text(msg, style="bold red"))

    def _build_player_view(self, player):
        """播放主界面。"""
        current = self.queue.current()

        header = Text()
        header.append(f" {APP_NAME}", style="bold cyan")
        header.append(" | ", style="dim")
        header.append(self.queue.get_mode_label(), style="yellow")

        if current:
            status_icon = "‖" if player.is_paused() else "▶"
            song_name = current.get("name", "未知歌曲")
            artist = current.get("artist", "未知歌手")

            pos = player.get_position()
            dur = player.get_duration() or current.get("duration", 0) / 1000.0

            bar = make_progress_bar(pos, dur)

            play_text = Text()
            play_text.append(f"  {status_icon} ", style="bold green")
            play_text.append(song_name, style="bold white")
            play_text.append(f" - {artist}", style="cyan")

            progress_text = Text()
            progress_text.append(f"   {bar} ", style="green")
            progress_text.append(f"{format_duration(pos)}/{format_duration(dur)}", style="dim")
            progress_text.append(f"  Vol:{int(player.get_volume())}", style="yellow")
        else:
            # 用 DejaVu 等常见等宽字体一定包含的字符，避免显示成方块(tofu)。
            # ⏹(U+23F9) / ⏸(U+23F8) 在树莓派默认字体里缺失。
            play_text = Text()
            play_text.append("  ■ ", style="yellow")
            play_text.append("空闲中...", style="white")
            progress_text = Text()
            progress_text.append("   " + "░" * 25 + " ", style="green")
            progress_text.append("00:00/00:00", style="dim")

        # 队列预览
        queue_table = Table(
            show_header=True, header_style="bold dim",
            border_style="dim", expand=True, box=None, pad_edge=False,
        )
        queue_table.add_column("#", style="dim", width=4)
        queue_table.add_column("歌曲", style="white")
        queue_table.add_column("歌手", style="cyan")
        queue_table.add_column("时长", style="dim", justify="right", width=7)

        display = self.queue.get_display_list(window=8)
        if display:
            for idx, song, is_current in display:
                marker = "▶" if is_current else " "
                name_style = "bold green" if is_current else "white"
                queue_table.add_row(
                    f"{marker}{idx + 1}",
                    Text(song.get("name", ""), style=name_style),
                    song.get("artist", ""),
                    format_duration(song.get("duration", 0) / 1000),
                )
        else:
            queue_table.add_row("", Text("（队列为空，按 s 搜索）", style="dim"), "", "")

        # 快捷键提示（窄终端自动分两行）
        helps = [
            ("空格", "暂停"), ("n", "下首"), ("p", "上首"), ("s", "搜索"),
            ("P", "歌单"), ("l", "歌词"), ("r", "模式"), ("↑↓", "音量"),
            ("Q", "队列"), ("q", "退出"),
        ]

        def build_help(items):
            t = Text()
            for i, (key, desc) in enumerate(items):
                t.append(f"{key}", style="bold yellow")
                t.append(f" {desc}", style="dim")
                if i < len(items) - 1:
                    t.append("  ", style="dim")
            return t

        def est_width(items):
            w = 0
            for key, desc in items:
                for ch in key + " " + desc:
                    w += 2 if ord(ch) > 127 else 1
                w += 2
            return w

        if est_width(helps) <= self.console.width:
            help_text = build_help(helps)
        else:
            mid = (len(helps) + 1) // 2
            help_text = Text()
            help_text.append_text(build_help(helps[:mid]))
            help_text.append("\n")
            help_text.append_text(build_help(helps[mid:]))

        parts = [
            Align.center(header),
            Text(""),
            play_text,
            progress_text,
            Text(""),
            Panel(queue_table, title="播放队列", border_style="dim"),
            Text(""),
            help_text,
        ]
        msg_line = self._message_line()
        if msg_line is not None:
            parts.append(msg_line)
        return Group(*parts)

    def _build_search_view(self):
        """搜索结果界面。"""
        if not self.search_results:
            return Group(
                Text("搜索结果为空", style="dim"),
                Text(""),
                Text("s 重新搜索，ESC 返回", style="dim"),
            )

        table = Table(
            title="搜索结果", show_header=True,
            header_style="bold cyan", border_style="cyan", expand=True,
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("歌曲", style="white", min_width=16)
        table.add_column("歌手", style="cyan")
        table.add_column("专辑", style="dim")
        table.add_column("时长", style="dim", justify="right", width=7)

        for i, song in enumerate(self.search_results):
            table.add_row(
                str(i + 1),
                song.get("name", ""),
                song.get("artist", ""),
                song.get("album", ""),
                format_duration(song.get("duration", 0) / 1000),
            )

        parts = [table, Text(""), Text("输入序号播放，s 重新搜索，ESC 返回", style="dim")]
        msg_line = self._message_line()
        if msg_line is not None:
            parts.append(msg_line)
        return Group(*parts)

    def _build_playlist_view(self):
        """歌单界面。"""
        if self.playlist_tracks:
            table = Table(
                title=f"歌单歌曲 ({len(self.playlist_tracks)}首)",
                show_header=True, header_style="bold cyan",
                border_style="cyan", expand=True,
            )
            table.add_column("#", style="dim", width=4)
            table.add_column("歌曲", style="white", min_width=16)
            table.add_column("歌手", style="cyan")
            table.add_column("时长", style="dim", justify="right", width=7)

            for i, song in enumerate(self.playlist_tracks):
                table.add_row(
                    str(i + 1),
                    song.get("name", ""),
                    song.get("artist", ""),
                    format_duration(song.get("duration", 0) / 1000),
                )

            parts = [table, Text(""), Text("输入序号播放，ESC 返回", style="dim")]
        elif self.playlists:
            table = Table(
                title="我的歌单", show_header=True,
                header_style="bold cyan", border_style="cyan", expand=True,
            )
            table.add_column("#", style="dim", width=4)
            table.add_column("歌单名", style="white", min_width=16)
            table.add_column("歌曲数", style="cyan", justify="right", width=7)
            table.add_column("创建者", style="dim")

            for i, pl in enumerate(self.playlists):
                table.add_row(
                    str(i + 1),
                    pl.get("name", ""),
                    str(pl.get("track_count", 0)),
                    pl.get("creator", ""),
                )

            parts = [table, Text(""), Text("输入序号查看歌曲，ESC 返回", style="dim")]
        else:
            parts = [Text("暂无歌单", style="dim"), Text(""), Text("ESC 返回", style="dim")]

        msg_line = self._message_line()
        if msg_line is not None:
            parts.append(msg_line)
        return Group(*parts)

    def _build_lyric_view(self, player):
        """歌词界面。"""
        if not self.lyric_lines:
            return Group(
                Text("暂无歌词", style="dim"),
                Text(""),
                Text("ESC 返回", style="dim"),
            )

        pos = player.get_position()
        current_line = self._current_lyric_index(pos)

        window = 7
        start = max(0, current_line - window // 2)
        end = min(len(self.lyric_lines), start + window)
        if end - start < window:
            start = max(0, end - window)

        lines = []
        for i in range(start, end):
            if i == current_line:
                lines.append(Text(f"  ♪ {self.lyric_lines[i]}", style="bold green"))
            else:
                lines.append(Text(f"    {self.lyric_lines[i]}", style="dim"))

        current = self.queue.current()
        title = (
            f"🎵 {current.get('name', '')} - {current.get('artist', '')}"
            if current else "歌词"
        )

        body = Group(*lines) if lines else Text("", style="dim")
        return Group(
            Panel(Align.center(body), title=title, border_style="cyan"),
            Text(""),
            Text("ESC 返回", style="dim"),
        )

    def _build_queue_view(self):
        """完整播放队列。"""
        if self.queue.is_empty():
            return Group(
                Text("播放队列为空", style="dim"),
                Text(""),
                Text("ESC 返回", style="dim"),
            )

        table = Table(
            title=f"播放队列 ({len(self.queue)}首) - {self.queue.get_mode_label()}",
            show_header=True, header_style="bold cyan",
            border_style="cyan", expand=True,
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("歌曲", style="white", min_width=16)
        table.add_column("歌手", style="cyan")
        table.add_column("时长", style="dim", justify="right", width=7)

        for i, song in enumerate(self.queue.queue):
            marker = "▶ " if i == self.queue.current_index else "  "
            name_style = "bold green" if i == self.queue.current_index else "white"
            table.add_row(
                f"{marker}{i + 1}",
                Text(song.get("name", ""), style=name_style),
                song.get("artist", ""),
                format_duration(song.get("duration", 0) / 1000),
            )

        return Group(table, Text(""), Text("ESC 返回", style="dim"))

    # ---- 歌词解析 ----

    def set_lyric(self, lyric_text: str):
        """解析 LRC 格式歌词。"""
        self.lyric_lines = []
        self.lyric_times = []

        if not lyric_text:
            return

        import re
        pattern = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\](.*)")

        for line in lyric_text.split("\n"):
            match = pattern.match(line)
            if match:
                m = int(match.group(1))
                s = int(match.group(2))
                ms = int(match.group(3) or 0)
                text = match.group(4).strip()
                total = m * 60 + s + ms / 1000.0
                self.lyric_times.append(total)
                self.lyric_lines.append(text if text else "♪")

        # 如果歌词为空（没时间标签），直接按行显示
        if not self.lyric_lines:
            self.lyric_lines = [
                line.strip() for line in lyric_text.split("\n") if line.strip()
            ]
            self.lyric_times = [0.0] * len(self.lyric_lines)
