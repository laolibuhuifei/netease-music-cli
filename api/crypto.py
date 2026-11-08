"""网易云 weapi 加密算法实现。

网易云 API 使用 AES-128-CBC + RSA 双重加密。
这里用 pycryptodome 实现，纯 Python，无外部依赖。
"""

import base64
import binascii
import json
import os

# 兼容两种 pycryptodome 发行版：
#   - pip 安装:       from Crypto.Cipher import AES
#   - Debian/Raspbian apt 包 python3-pycryptodome: from Cryptodome.Cipher import AES
try:
    from Crypto.Cipher import AES
except ImportError:  # pragma: no cover
    from Cryptodome.Cipher import AES

# 网易云预设密钥
# ref: https://github.com/Binaryify/neteaseCloudMusicApi
preset_key = b"0CoJUm6Qyw8W8jud"
iv = b"0102030405060708"

# RSA 公钥指数和模数 (网易固定使用)
# n 是 1024-bit RSA 模数，十六进制表示
e = "010001"
n = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
    "3ece0462db0a22b8e7"
)


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    """PKCS7 填充。"""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _aes_encrypt(text: str, key: bytes) -> str:
    """AES-128-CBC 加密，返回 base64。"""
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = _pkcs7_pad(text.encode("utf-8"))
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("utf-8")


def _generate_random_key() -> str:
    """生成 16 字节随机密钥（base64 编码）。"""
    random_bytes = os.urandom(16)
    # 网易用的是自定义的 base64 变体，字符集为 a-zA-Z0-9
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    result = ""
    for b in random_bytes:
        result += chars[b % len(chars)]
    return result


def _rsa_encrypt(random_key: str) -> str:
    """RSA 加密随机密钥。"""
    # 网易的 RSA 实现有点特殊： reversed + hex
    text = random_key[::-1]  # 反转字符串
    # 转成 hex
    text_hex = binascii.hexlify(text.encode("utf-8")).decode("utf-8")
    # 用大整数做模幂
    rs = pow(
        int(text_hex, 16),
        int(e, 16),
        int(n, 16),
    )
    return format(rs, "0256x")


def weapi_encrypt(payload: dict) -> dict:
    """weapi 加密入口。

    输入原始 payload dict，返回加密后的 params（可直接 POST）。
    """
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    random_key = _generate_random_key()

    # 两次 AES：先用 preset_key，再用 random_key
    enc1 = _aes_encrypt(text, preset_key)
    enc2 = _aes_encrypt(enc1, random_key.encode("utf-8"))

    # RSA 加密 random_key
    enc_key = _rsa_encrypt(random_key)

    return {
        "params": enc2,
        "encSecKey": enc_key,
    }
