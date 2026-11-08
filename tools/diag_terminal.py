#!/usr/bin/env python3
"""诊断 TUI 在不同终端尺寸 / TERM 下的渲染情况。"""

import fcntl
import os
import pty
import re
import select
import struct
import termios
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录


def strip_ansi(b: bytes) -> str:
    s = b.decode("utf-8", errors="ignore")
    s = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
    s = re.sub(r"\x1b\][^\x07]*\x07", "", s)
    s = re.sub(r"\x1b[()][A-B0-2]", "", s)
    return s


def run(cols, rows, term="xterm-256color", wait=4.0, argv=None):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(HERE)
        os.environ["PYTHONPATH"] = HERE
        os.environ["TERM"] = term
        os.environ["COLUMNS"] = str(cols)
        os.environ["LINES"] = str(rows)
        try:
            os.execvp("python3", ["python3"] + (argv or ["main.py"]))
        except Exception:
            os._exit(127)

    # 设置 pty 窗口大小
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception as e:
        print("  (设置窗口大小失败:", e, ")")

    out = b""
    start = time.time()
    while time.time() - start < wait:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                d = os.read(fd, 65536)
                if not d:
                    break
                out += d
            except OSError:
                break

    try:
        os.write(fd, b"q")
    except OSError:
        pass
    time.sleep(0.8)
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass

    return out


def main():
    # 先看应用在 dumb 终端下自己检测到什么
    print("#" * 62)
    print("# 在 pty 中运行 `main.py diag`（TERM=dumb）")
    print("#" * 62)
    out = run(80, 24, "dumb", wait=8.0, argv=["main.py", "diag"])
    print(strip_ansi(out))
    print()

    cases = [
        (80, 24, "xterm-256color"),
        (80, 24, "dumb"),
        (80, 24, "linux"),
        (60, 18, "xterm-256color"),
        (40, 12, "xterm-256color"),
        (100, 30, "screen-256color"),
    ]

    for cols, rows, term in cases:
        print("=" * 62)
        print(f"终端 {cols}x{rows}  TERM={term}")
        print("=" * 62)
        out = run(cols, rows, term, wait=(10.0 if term == "dumb" else 4.0))
        text = strip_ansi(out)
        lines = [ln.rstrip() for ln in text.split("\n")]
        # 找出有实际内容的行
        content = [ln for ln in lines if ln.strip()]
        print(f"  原始字节: {len(out)} | 去ANSI后非空行: {len(content)}")
        if content:
            print("  前 8 行:")
            for ln in content[:8]:
                print("    |" + ln[:76])
        else:
            print("  >>> 没有任何可见内容（空白）")
            print("  原始内容 repr:", repr(out[:600]))
        print()


if __name__ == "__main__":
    main()
