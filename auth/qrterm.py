"""纯 Python 二维码生成与终端渲染，无任何第三方依赖。

为低性能设备（树莓派 Zero 2W 等）设计：不装 qrcode / qrencode / 浏览器，
也能直接在终端里把二维码画出来扫。

只实现本项目需要的范围：
  - byte 模式（UTF-8 字节）
  - 纠错等级 L
  - 版本 1~10（最大约 271 字节，登录 URL 通常 51 字节，够用）

渲染用半块字符（▀ ▄ █ + 空格），一个字符宽 = 1 模块，高 = 2 模块，
配合黑前景 / 白背景的 ANSI 颜色，得到标准黑白二维码。
"""

# ---- 纠错等级 L 的分块表 ----
# 版本: (每块纠错码字数, [(块数, 每块数据码字数), ...])
_RS_BLOCKS_L = {
    1:  (7,  [(1, 19)]),
    2:  (10, [(1, 34)]),
    3:  (15, [(1, 55)]),
    4:  (20, [(1, 80)]),
    5:  (26, [(1, 108)]),
    6:  (18, [(2, 68)]),
    7:  (20, [(2, 78)]),
    8:  (24, [(2, 97)]),
    9:  (30, [(2, 116)]),
    10: (18, [(2, 68), (2, 69)]),
}

# 校正图案中心坐标
_ALIGN_POS = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30),
    6: (6, 34), 7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46),
    10: (6, 28, 50),
}

_ECL_L_BITS = 0b01  # 纠错等级 L 在格式信息里的两位编码

# ---- GF(256) 运算表 ----
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_v = 1
for _i in range(255):
    _GF_EXP[_i] = _v
    _GF_LOG[_v] = _i
    _v <<= 1
    if _v & 0x100:
        _v ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(degree: int) -> list:
    """生成 Reed-Solomon 生成多项式系数（最高次在末尾省略）。"""
    poly = [1]
    for i in range(degree):
        # 乘以 (x - a^i)
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gf_mul(c, _GF_EXP[i])
        poly = nxt
    return poly


def _rs_ecc(data: list, degree: int) -> list:
    """计算一段数据的 RS 纠错码字。"""
    gen = _rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(degree):
            rem[i] ^= _gf_mul(gen[i + 1], factor)
    return rem


def _bit_len(data_len: int, version: int) -> int:
    """字符计数字段位数：版本 1-9 为 8 位，10-26 为 16 位。"""
    return 8 if version <= 9 else 16


def _data_capacity(version: int) -> int:
    ec, groups = _RS_BLOCKS_L[version]
    return sum(n * d for n, d in groups)


def _pick_version(data_len: int) -> int:
    for v in range(1, 11):
        need_bits = 4 + _bit_len(data_len, v) + data_len * 8
        if need_bits <= _data_capacity(v) * 8:
            return v
    raise ValueError(f"内容过长（{data_len} 字节），超出二维码版本 10 的容量")


def _build_codewords(data: bytes, version: int) -> list:
    """组装最终码字序列（数据 + 纠错，按块交织）。"""
    capacity = _data_capacity(version)
    bits = []

    def push(value, length):
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)                      # byte 模式
    push(len(data), _bit_len(len(data), version))
    for b in data:
        push(b, 8)

    # 终止符（最多 4 个 0）
    for _ in range(min(4, capacity * 8 - len(bits))):
        bits.append(0)
    # 补齐到字节
    while len(bits) % 8:
        bits.append(0)

    codewords = [int("".join(map(str, bits[i:i + 8])), 2)
                 for i in range(0, len(bits), 8)]
    # 填充字节 0xEC / 0x11 交替
    pad = (0xEC, 0x11)
    i = 0
    while len(codewords) < capacity:
        codewords.append(pad[i % 2])
        i += 1

    # 按块拆分
    ec_len, groups = _RS_BLOCKS_L[version]
    blocks = []
    pos = 0
    for num, dlen in groups:
        for _ in range(num):
            blocks.append(codewords[pos:pos + dlen])
            pos += dlen

    eccs = [_rs_ecc(b, ec_len) for b in blocks]

    # 交织：先交错数据，再交错纠错
    out = []
    max_dlen = max(len(b) for b in blocks)
    for i in range(max_dlen):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_len):
        for e in eccs:
            out.append(e[i])
    return out


class _Matrix:
    """二维码矩阵，区分功能模块（不参与掩码）。"""

    def __init__(self, version: int):
        self.version = version
        self.size = 17 + 4 * version
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x, y, dark, fixed=True):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.mod[y][x] = dark
            if fixed:
                self.fixed[y][x] = True

    # ---- 功能图案 ----

    def draw_finder(self, cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                dist = max(abs(dx), abs(dy))
                self.set(cx + dx, cy + dy, dist not in (2, 4))

    def draw_alignment(self, cx, cy):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    def draw_function_patterns(self):
        n = self.size
        # 时序图案
        for i in range(n):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        # 三个定位图案
        self.draw_finder(3, 3)
        self.draw_finder(n - 4, 3)
        self.draw_finder(3, n - 4)
        # 校正图案
        pos = _ALIGN_POS[self.version]
        for cy in pos:
            for cx in pos:
                # 跳过与定位图案重叠的位置
                if (cx == 6 and cy == 6) or \
                   (cx == 6 and cy == n - 7) or \
                   (cx == n - 7 and cy == 6):
                    continue
                self.draw_alignment(cx, cy)
        # 预留格式信息区（注意跳过 x=6 / y=6 的时序图案，那里不放格式位）
        for i in range(9):
            if i != 6:
                self.set(8, i, False)
                self.set(i, 8, False)
        for i in range(8):
            self.set(n - 1 - i, 8, False)
        for i in range(7):
            self.set(8, n - 7 + i, False)
        # 固定的深色模块，必须先占位，否则数据会写进去
        self.set(8, n - 8, True)
        # 版本信息（版本 7 起）
        if self.version >= 7:
            bits = self._version_bits(self.version)
            for i in range(18):
                dark = (bits >> i) & 1 == 1
                a = n - 11 + i % 3
                b = i // 3
                self.set(a, b, dark)
                self.set(b, a, dark)

    @staticmethod
    def _version_bits(version: int) -> int:
        rem = version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        return version << 12 | rem

    def draw_format_bits(self, mask: int):
        data = _ECL_L_BITS << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        n = self.size

        def bit(i):
            return (bits >> i) & 1 == 1

        # 第一份：左上角
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        # 第二份：右上 + 左下
        for i in range(8):
            self.set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, n - 15 + i, bit(i))
        # 固定的深色模块
        self.set(8, n - 8, True)

    def place_data(self, codewords: list):
        bits = []
        for c in codewords:
            for i in range(7, -1, -1):
                bits.append((c >> i) & 1)

        idx = 0
        col = self.size - 1
        upward = True
        while col > 0:
            if col == 6:      # 跳过竖向时序列
                col -= 1
            rows = range(self.size - 1, -1, -1) if upward else range(self.size)
            for y in rows:
                for dx in range(2):
                    x = col - dx
                    if not self.fixed[y][x]:
                        dark = False
                        if idx < len(bits):
                            dark = bits[idx] == 1
                            idx += 1
                        self.mod[y][x] = dark
            upward = not upward
            col -= 2

    # ---- 掩码 ----

    def apply_mask(self, mask: int):
        for y in range(self.size):
            for x in range(self.size):
                if self.fixed[y][x]:
                    continue
                if _mask_bit(mask, x, y):
                    self.mod[y][x] = not self.mod[y][x]

    def penalty(self) -> int:
        n = self.size
        score = 0

        # 规则 1：同色连续 >= 5
        for line in list(self.mod) + [list(col) for col in zip(*self.mod)]:
            run = 1
            for i in range(1, n):
                if line[i] == line[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1
            if run >= 5:
                score += 3 + (run - 5)

        # 规则 2：2x2 同色块
        for y in range(n - 1):
            for x in range(n - 1):
                c = self.mod[y][x]
                if c == self.mod[y][x + 1] == self.mod[y + 1][x] == self.mod[y + 1][x + 1]:
                    score += 3

        # 规则 3：形如 1:1:3:1:1 且一侧有 4 空白
        pattern = [True, False, True, True, True, False, True]
        for line in list(self.mod) + [list(col) for col in zip(*self.mod)]:
            for i in range(n - 6):
                if line[i:i + 7] == pattern:
                    before = line[max(0, i - 4):i]
                    after = line[i + 7:i + 11]
                    if len(before) < 4 or not any(before):
                        score += 40
                    if len(after) < 4 or not any(after):
                        score += 40

        # 规则 4：深浅比例偏离 50%
        dark = sum(sum(1 for c in row if c) for row in self.mod)
        total = n * n
        ratio = dark * 100 // total
        score += abs(ratio - 50) // 5 * 10
        return score

    def snapshot(self):
        return [row[:] for row in self.mod]


def _mask_bit(mask: int, x: int, y: int) -> bool:
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (y // 2 + x // 3) % 2 == 0
    if mask == 5:
        return (x * y) % 2 + (x * y) % 3 == 0
    if mask == 6:
        return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    if mask == 7:
        return ((x + y) % 2 + (x * y) % 3) % 2 == 0
    raise ValueError(mask)


def make_matrix(text: str, version: int = 0, mask: int = -1):
    """生成二维码矩阵。

    Args:
        text: 内容（按 UTF-8 编码）
        version: 0 表示自动选择
        mask: -1 表示自动选最优掩码

    Returns:
        (matrix, version, mask)，matrix 为 bool 二维列表，True 表示深色
    """
    data = text.encode("utf-8")
    if version <= 0:
        version = _pick_version(len(data))
    if len(data) > _data_capacity(version) - (2 if version <= 9 else 3):
        raise ValueError("内容超出该版本容量")

    codewords = _build_codewords(data, version)

    best = None
    masks = range(8) if mask < 0 else [mask]
    for m in masks:
        mtx = _Matrix(version)
        mtx.draw_function_patterns()
        mtx.place_data(codewords)
        mtx.apply_mask(m)
        mtx.draw_format_bits(m)
        p = mtx.penalty()
        if best is None or p < best[0]:
            best = (p, mtx.snapshot(), m)
    return best[1], version, best[2]


def render_lines(matrix, quiet: int = 4, color: bool = True):
    """把矩阵渲染成终端文本行（半块字符，一行 = 2 模块高）。"""
    n = len(matrix)
    total = n + quiet * 2

    # 补上静默区
    grid = []
    for _ in range(quiet):
        grid.append([False] * total)
    for row in matrix:
        grid.append([False] * quiet + list(row) + [False] * quiet)
    for _ in range(quiet):
        grid.append([False] * total)

    # 高度补齐为偶数
    if len(grid) % 2:
        grid.append([False] * total)

    prefix = "\x1b[30;47m" if color else ""
    suffix = "\x1b[0m" if color else ""

    lines = []
    for i in range(0, len(grid), 2):
        top, bottom = grid[i], grid[i + 1]
        buf = []
        for x in range(total):
            t, b = top[x], bottom[x]
            if t and b:
                buf.append("█")
            elif t:
                buf.append("▀")
            elif b:
                buf.append("▄")
            else:
                buf.append(" ")
        lines.append(prefix + "".join(buf) + suffix)
    return lines


def terminal_qr(text: str, stream=None) -> bool:
    """直接在终端打印二维码 + 原始链接。成功返回 True。"""
    import shutil
    import sys

    stream = stream or sys.stdout
    color = getattr(stream, "isatty", lambda: False)()

    try:
        matrix, version, mask = make_matrix(text)
    except Exception:
        return False

    # 根据终端高度自动决定静默区宽度（4 是标准，太挤时退到 2）
    rows = (len(matrix) + 8 + 1) // 2 + 6
    quiet = 4
    try:
        term_h = shutil.get_terminal_size((80, 24)).lines
    except Exception:
        term_h = 24
    if rows > term_h:
        quiet = 2

    for line in render_lines(matrix, quiet=quiet, color=color):
        print(line, file=stream)
        # 某些终端背景色会被下一行覆盖，显式换行即可
    stream.flush()
    return True
