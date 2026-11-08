"""播放队列管理。

支持顺序播放、单曲循环、随机播放三种模式。
"""

import random
from typing import Optional


class PlayQueue:
    """播放队列。"""

    # 播放模式
    MODE_ORDER = "order"
    MODE_REPEAT_ONE = "repeat-one"
    MODE_RANDOM = "random"

    MODE_LABELS = {
        MODE_ORDER: "顺序播放",
        MODE_REPEAT_ONE: "单曲循环",
        MODE_RANDOM: "随机播放",
    }

    MODE_ORDER_LIST = [MODE_ORDER, MODE_REPEAT_ONE, MODE_RANDOM]

    def __init__(self, mode: str = MODE_ORDER):
        self.queue: list = []  # 歌曲列表 [{id, name, artist, album, duration}, ...]
        self.current_index: int = -1
        self.mode: str = mode
        self._history: list = []  # 播放历史（用于上一首）
        self._random_played: set = set()  # 随机模式下已播放的索引

    # ---- 队列操作 ----

    def clear(self):
        """清空队列。"""
        self.queue.clear()
        self.current_index = -1
        self._history.clear()
        self._random_played.clear()

    def add(self, song: dict):
        """添加单首歌到队列末尾。"""
        self.queue.append(song)

    def add_list(self, songs: list):
        """添加多首歌到队列。"""
        self.queue.extend(songs)

    def replace(self, songs: list, start_index: int = 0):
        """替换整个队列并从指定位置开始播放。"""
        self.clear()
        self.queue.extend(songs)
        self.current_index = start_index - 1  # next() 会 +1

    def remove(self, index: int):
        """移除指定位置的歌曲。"""
        if 0 <= index < len(self.queue):
            removed = self.queue.pop(index)
            if index < self.current_index:
                self.current_index -= 1
            elif index == self.current_index:
                self.current_index = min(self.current_index, len(self.queue) - 1)
            return removed
        return None

    def __len__(self):
        return len(self.queue)

    def is_empty(self):
        return len(self.queue) == 0

    # ---- 播放导航 ----

    def current(self) -> Optional[dict]:
        """获取当前歌曲。"""
        if 0 <= self.current_index < len(self.queue):
            return self.queue[self.current_index]
        return None

    def next(self) -> Optional[dict]:
        """获取下一首歌并移动指针。"""
        if not self.queue:
            return None

        if self.mode == self.MODE_REPEAT_ONE:
            # 单曲循环：不移动指针
            return self.current()

        if self.mode == self.MODE_RANDOM:
            # 随机：从未播放的里面选
            available = [
                i for i in range(len(self.queue))
                if i not in self._random_played
            ]
            if not available:
                # 全部播放完毕，重置
                self._random_played.clear()
                available = list(range(len(self.queue)))
            if self.current_index >= 0:
                self._random_played.add(self.current_index)
            chosen = random.choice(available)
            self._history.append(self.current_index)
            self.current_index = chosen
            return self.queue[chosen]

        # 顺序播放
        self._history.append(self.current_index)
        self.current_index += 1
        if self.current_index >= len(self.queue):
            # 播放完毕
            self.current_index = 0
            return None  # 返回 None 表示队列播放完毕
        return self.queue[self.current_index]

    def prev(self) -> Optional[dict]:
        """获取上一首歌并移动指针。"""
        if not self.queue:
            return None

        if self._history and self.mode != self.MODE_RANDOM:
            self.current_index = self._history.pop()
            return self.queue[self.current_index]

        # 没有历史记录就从头来
        self.current_index = max(0, self.current_index - 1)
        return self.current()

    def jump_to(self, index: int) -> Optional[dict]:
        """跳转到队列中指定位置。"""
        if 0 <= index < len(self.queue):
            if self.current_index >= 0:
                self._history.append(self.current_index)
            self.current_index = index
            return self.queue[index]
        return None

    # ---- 模式切换 ----

    def cycle_mode(self) -> str:
        """切换播放模式，返回新模式。"""
        idx = self.MODE_ORDER_LIST.index(self.mode)
        self.mode = self.MODE_ORDER_LIST[(idx + 1) % len(self.MODE_ORDER_LIST)]
        self._random_played.clear()
        return self.mode

    def set_mode(self, mode: str):
        """设置播放模式。"""
        if mode in self.MODE_ORDER_LIST:
            self.mode = mode
            self._random_played.clear()

    def get_mode_label(self) -> str:
        return self.MODE_LABELS.get(self.mode, "未知")

    # ---- 信息 ----

    def get_display_list(self, window: int = 10) -> list:
        """获取用于显示的队列列表（窗口式，减少内存/渲染压力）。

        返回 [(index, song, is_current), ...]
        """
        if not self.queue:
            return []

        start = max(0, self.current_index - window // 2)
        end = min(len(self.queue), start + window)
        # 调整 start 以保证足够数量
        if end - start < window:
            start = max(0, end - window)

        result = []
        for i in range(start, end):
            result.append((i, self.queue[i], i == self.current_index))
        return result
