#!/usr/bin/env python3
"""auth.qrterm 的回归测试。

不依赖任何第三方库：这些指纹是用参考实现（qrcode 库）逐位比对确认过的，
这里只保证以后改动不会悄悄改坏编码结果。

跑法：
    python3 -m unittest discover -s tests -v
"""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.qrterm import _pick_version, make_matrix, render_lines  # noqa: E402


def _fingerprint(matrix) -> str:
    blob = "".join("1" if cell else "0" for row in matrix for cell in row).encode()
    return hashlib.sha256(blob).hexdigest()


class TestQrEncode(unittest.TestCase):
    # (内容, 版本, 掩码, 矩阵指纹)
    # 指纹已与 qrcode 库在版本 1~10 × 8 种掩码下逐位比对确认
    KNOWN = [
        ("hello", 1, 7,
         "d591b9a8e941c643b54e2fa15b632976d6484ba5875f37ef715544b1e96a7baf"),
        ("netease-music-cli", 1, 7,
         "bffdf7ceffdeebdd8c44ceff9aca11d85044c8a2849007be73bad25bf40431d9"),
        ("https://music.163.com/login?codekey=c915515e-8c44-4007-9ddd-7d7d9e6dc0f8", 4, 2,
         "b70b3641c7e25cb2fc2cc68bdd75b3650af82372d2cf72d2119e8cfbc3b23bb6"),
    ]

    def test_known_matrices(self):
        for text, version, mask, digest in self.KNOWN:
            with self.subTest(text=text):
                matrix, v, m = make_matrix(text)
                self.assertEqual(v, version)
                self.assertEqual(m, mask)
                self.assertEqual(_fingerprint(matrix), digest)

    def test_size_follows_version(self):
        for version in range(1, 11):
            matrix, v, _ = make_matrix("x" * 10, version=version)
            self.assertEqual(v, version)
            self.assertEqual(len(matrix), 17 + 4 * version)
            self.assertTrue(all(len(row) == len(matrix) for row in matrix))

    def test_auto_version_picks_smallest(self):
        # 1 字节内容用最小版本
        self.assertEqual(_pick_version(1), 1)
        # 版本边界：v1 容量 19 字节，模式头 4 位 + 计数 8 位 + 4 位终止符
        self.assertEqual(_pick_version(17), 1)
        self.assertEqual(_pick_version(20), 2)

    def test_utf8_payload(self):
        matrix, v, _ = make_matrix("晴天")
        self.assertEqual(len(matrix), 17 + 4 * v)
        self.assertEqual(v, 1)

    def test_render_roundtrip(self):
        """把渲染出的字符反解回矩阵，应与原矩阵完全一致。"""
        matrix, _, _ = make_matrix("https://music.163.com/login?codekey=abc")
        for quiet in (2, 4):
            lines = render_lines(matrix, quiet=quiet, color=False)
            rows = []
            for line in lines:
                rows.append([ch in "█▀" for ch in line])
                rows.append([ch in "█▄" for ch in line])
            core = [r[quiet:quiet + len(matrix)] for r in rows[quiet:quiet + len(matrix)]]
            expected = [[bool(c) for c in row] for row in matrix]
            self.assertEqual(core, expected, f"quiet={quiet} 往返还原失败")

    def test_render_width(self):
        matrix, _, _ = make_matrix("hello")
        lines = render_lines(matrix, quiet=4, color=False)
        self.assertEqual(len(lines[0]), len(matrix) + 8)
        self.assertEqual(len(lines), (len(matrix) + 8 + 1) // 2)

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            make_matrix("x" * 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
