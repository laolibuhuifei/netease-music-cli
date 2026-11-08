#!/usr/bin/env python3
"""用真实 pty 测试 TUI 按键处理与重绘行为。

pty.fork() 分配的伪终端与真实终端行为一致，termios 有效，
可以可靠地验证按键是否被处理。
"""

import fcntl
import os
import pty
import select
import struct
import termios
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录
PTY_COLS, PTY_ROWS = 100, 30


def run_session(script, timeout=25, label=""):
    """在 pty 中运行 main.py，按 script 发送按键。

    script: [(等待秒数, 按键bytes), ...]
    返回 (输出bytes, 是否正常退出, 退出耗时)
    """
    pid, fd = pty.fork()
    if pid == 0:
        # 子进程
        os.chdir(HERE)
        os.environ["PYTHONPATH"] = HERE
        os.environ["TERM"] = "xterm-256color"
        try:
            os.execvp("python3", ["python3", "main.py"])
        except Exception:
            os._exit(127)

    out = b""
    start = time.time()
    # pty.fork() 新建的伪终端窗口尺寸默认是 0x0，不继承父终端。
    # 不显式设置的话 rich 会因为 0 尺寸而什么都不画，测试结果失真。
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", PTY_ROWS, PTY_COLS, 0, 0))
    except OSError:
        pass
    idx = 0
    next_at = start + (script[0][0] if script else 1e9)
    exited = None
    exit_time = None

    while time.time() - start < timeout:
        now = time.time()

        # 到点发按键
        if idx < len(script) and now >= next_at:
            try:
                os.write(fd, script[idx][1])
            except OSError:
                pass
            idx += 1
            if idx < len(script):
                next_at = now + script[idx][0]

        # 读输出
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                data = os.read(fd, 65536)
                if data:
                    out += data
            except OSError:
                pass

        # 检查子进程是否退出
        wpid, status = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            exited = status
            exit_time = time.time() - start
            # 把剩余输出读干净
            while True:
                r, _, _ = select.select([fd], [], [], 0.2)
                if not r:
                    break
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                out += data
            break

    if exited is None:
        # 超时，强制结束
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass

    try:
        os.close(fd)
    except OSError:
        pass

    return out, exited is not None, exit_time


def strip_ansi(b: bytes) -> str:
    import re
    s = b.decode("utf-8", errors="ignore")
    s = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
    s = re.sub(r"\x1b\][^\x07]*\x07", "", s)
    s = re.sub(r"\x1b[()][A-B0-2]", "", s)
    return s


def main():
    print("=" * 62)
    print(" TUI 按键 / 重绘测试（真实 pty）")
    print("=" * 62)

    # --- 测试 1：按 q 退出 ---
    print("\n[测试1] 启动 3 秒后按 q，应在 5 秒内退出")
    out, exited, et = run_session([(3.0, b"q")], timeout=15)
    print(f"  退出: {exited} | 耗时: {et:.1f}s" if et else f"  退出: {exited} | 超时被杀")
    print(f"  输出字节: {len(out)}")
    if exited and et and et < 8:
        print("  [OK] 按键 q 被正确响应")
    else:
        print("  [FAIL] 按键未生效")

    # --- 测试 2：s 打开搜索输入，ESC 取消后仍可退出 ---
    print("\n[测试2] 按 s 出现搜索提示，ESC 取消后按 q 应能退出")
    out, exited, et = run_session(
        [(2.5, b"s"), (1.5, b"\x1b"), (1.5, b"q")], timeout=20
    )
    text = strip_ansi(out)
    has_prompt = "搜索关键词" in text
    cancelled = "已取消" in text
    print(f"  出现搜索提示: {has_prompt} | 显示已取消: {cancelled} | 退出: {exited}")
    if has_prompt and exited:
        print("  [OK] 搜索输入可 ESC 取消，程序正常退出")
    else:
        print("  [FAIL] 搜索输入路径异常")

    # --- 测试 3：中文输入并搜索 ---
    print("\n[测试3] 输入中文「民谣」回车，应出现搜索结果")
    out, exited, et = run_session(
        [(2.5, b"s"), (1.0, "民谣".encode()), (0.3, b"\r"), (5.0, b"q")],
        timeout=25,
    )
    text = strip_ansi(out)
    got_result = "搜索结果" in text
    has_song = "宋冬野" in text or "马頔" in text or "陈鸿宇" in text
    print(f"  出现搜索结果页: {got_result} | 出现歌手名: {has_song} | 退出: {exited}")
    if got_result and has_song:
        print("  [OK] 中文输入与搜索正常")
    else:
        print("  [FAIL] 中文输入或搜索异常")

    # --- 测试 4：空闲重绘量（脏检查）---
    print("\n[测试4] 空闲 8 秒的输出量（应≈单次绘制约 6KB）")
    out, exited, et = run_session([(8.0, b"q")], timeout=20)
    print(f"  8 秒空闲输出字节: {len(out)}")

    # --- 测试 5：播放中的重绘频率 ---
    print("\n[测试5] 播放中的重绘频率（应约 1 次/秒）")
    out, exited, et = run_session(
        [
            (2.5, b"s"),
            (1.0, "民谣".encode()),
            (0.3, b"\r"),
            (5.0, b"1"),      # 选第 1 首播放
            (10.0, b"q"),     # 播放 10 秒后退出
        ],
        timeout=40,
    )
    text = strip_ansi(out)
    playing = "▶" in text
    # 统计进度条行出现的次数（每次重绘一行）
    frames = text.count("Vol:")
    print(f"  进入播放: {playing} | 进度条帧数: {frames} | 总字节: {len(out)}")
    if playing:
        # 10 秒播放 + 若干次视图切换
        if 8 <= frames <= 20:
            print(f"  [OK] 刷新频率约 {frames/10:.1f} 次/秒，符合预期（无高频重绘）")
        elif frames > 20:
            print(f"  [WARN] 刷新偏频繁: {frames} 帧")
        else:
            print(f"  [INFO] 帧数偏少: {frames}，可能歌曲未成功播放")
    else:
        print("  [FAIL] 未能进入播放状态")

    print("\n" + "=" * 62)


if __name__ == "__main__":
    main()
