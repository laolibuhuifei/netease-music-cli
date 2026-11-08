"""mpv 播放器封装。

通过 Unix socket 与 mpv IPC 通信，控制播放/暂停/进度/音量等。
mpv 是 C 写的高性能播放器，内存占用约 30-50MB。
Python 只做 IPC 调度，几乎不占额外内存。
"""

import json
import os
import socket
import subprocess
import time
from typing import Optional

from config import MPV_SOCKET


class MpvPlayer:
    """通过 IPC socket 控制 mpv 播放器。"""

    # mpv 不认识的设备名 -> 回退到 auto
    _INVALID_DEVICES = {"", "default", "sysdefault"}

    def __init__(self, audio_device: str = "auto", volume: int = 80):
        # 兼容旧配置里写的 "default"（ALSA 风格），mpv 会因此播放失败
        if audio_device in self._INVALID_DEVICES:
            audio_device = "auto"
        self.socket_path = MPV_SOCKET
        self.audio_device = audio_device
        self.volume = volume
        self.proc: Optional[subprocess.Popen] = None
        self.sock: Optional[socket.socket] = None
        self._request_id = 0

    # ---- 生命周期 ----

    def start(self):
        """启动 mpv 进程。"""
        # 清理旧 socket
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self.proc = subprocess.Popen(
            [
                "mpv",
                "--idle=yes",
                "--no-video",
                "--no-terminal",
                "--no-input-terminal",
                "--no-input-default-bindings",
                f"--audio-device={self.audio_device}",
                f"--input-ipc-server={self.socket_path}",
                f"--volume={self.volume}",
                "--no-config",  # 不加载用户配置，避免干扰
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 等待 socket 创建
        for _ in range(50):  # 最多等 5 秒
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("mpv IPC socket 启动超时")

        self._connect()

    def _connect(self):
        """连接到 mpv IPC socket。"""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        self.sock.settimeout(1.0)

    def stop(self):
        """停止 mpv 进程。"""
        if self.sock:
            try:
                self._send_raw({"command": ["quit"]})
            except Exception:
                pass
            self.sock.close()
            self.sock = None

        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=3)
            self.proc = None

        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    # ---- IPC 通信 ----

    def _send_raw(self, command: dict) -> dict:
        """发送原始 IPC 命令并读取响应。"""
        if not self.sock:
            raise RuntimeError("mpv 未连接")

        data = (json.dumps(command) + "\n").encode("utf-8")
        self.sock.sendall(data)

        # 读取响应（可能有多条，取最后一条或匹配 request_id 的）
        buffer = b""
        while True:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                # 尝试解析完整的 JSON 行
                if b"\n" in buffer:
                    lines = buffer.split(b"\n")
                    for line in lines[:-1]:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            resp = json.loads(line)
                            # 命令响应包含 request_id 或 error 字段
                            if "error" in resp:
                                return resp
                        except json.JSONDecodeError:
                            continue
                    buffer = lines[-1]
            except socket.timeout:
                return {"error": "timeout"}
            except ConnectionError:
                return {"error": "connection_closed"}

        return {"error": "no_response"}

    def _command(self, *args) -> dict:
        """发送 mpv command 列表。"""
        self._request_id += 1
        return self._send_raw({
            "command": list(args),
            "request_id": self._request_id,
        })

    def _get_property(self, name: str):
        """获取属性。"""
        resp = self._command("get_property", name)
        if resp.get("error") == "success":
            return resp.get("data")
        return None

    def _set_property(self, name: str, value):
        """设置属性。"""
        return self._command("set_property", name, value)

    # ---- 播放控制 ----

    def load_file(self, url: str, mode: str = "replace"):
        """加载文件播放。

        Args:
            url: 文件路径或网络URL
            mode: "replace"（替换当前）或 "append"（加入队列）
        """
        self._command("loadfile", url, mode)

    def play(self):
        """播放（取消暂停）。"""
        self._set_property("pause", False)

    def pause(self):
        """暂停。"""
        self._set_property("pause", True)

    def toggle_pause(self):
        """切换暂停/播放。"""
        current = self._get_property("pause")
        self._set_property("pause", not current)

    def stop_playback(self):
        """停止播放。"""
        self._command("stop")

    def seek(self, seconds: float, mode: str = "relative"):
        """跳转。

        Args:
            seconds: 跳转秒数
            mode: "relative"（相对）, "absolute"（绝对）, "relative-percent"
        """
        self._command("seek", seconds, mode)

    # ---- 状态查询 ----

    def is_paused(self) -> bool:
        return self._get_property("pause") or False

    def is_playing(self) -> bool:
        return not self.is_paused()

    def get_position(self) -> float:
        """当前播放位置（秒）。"""
        return self._get_property("time-pos") or 0.0

    def get_duration(self) -> float:
        """总时长（秒）。"""
        return self._get_property("duration") or 0.0

    def get_percent_pos(self) -> float:
        """播放进度百分比（0-100）。"""
        return self._get_property("percent-pos") or 0.0

    def get_title(self) -> str:
        """当前播放的媒体标题。"""
        return self._get_property("media-title") or ""

    def get_file_path(self) -> str:
        """当前播放的文件路径。"""
        return self._get_property("path") or ""

    # ---- 音量控制 ----

    def set_volume(self, volume: int):
        """设置音量 (0-100)。"""
        volume = max(0, min(100, volume))
        self._set_property("volume", volume)
        self.volume = volume

    def get_volume(self) -> int:
        return self._get_property("volume") or 0

    def volume_up(self, step: int = 5):
        self.set_volume(self.get_volume() + step)

    def volume_down(self, step: int = 5):
        self.set_volume(self.get_volume() - step)

    # ---- 事件监听 ----

    def poll_events(self) -> list:
        """读取 mpv 事件（非阻塞）。

        返回事件列表，常见事件：
        - "end-file": 播放结束
        - "idle": 空闲
        """
        if not self.sock:
            return []

        events = []
        self.sock.settimeout(0.01)  # 非阻塞
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                for line in chunk.decode("utf-8", errors="ignore").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if "event" in msg:
                            events.append(msg)
                    except json.JSONDecodeError:
                        continue
        except (socket.timeout, ConnectionError, BlockingIOError):
            pass
        finally:
            self.sock.settimeout(1.0)

        return events
