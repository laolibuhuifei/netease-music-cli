#!/bin/bash
# netease-music-cli 安装脚本
#
# 用法：
#   ./install.sh            # 安装系统依赖 + 创建命令
#   ./install.sh --no-apt   # 跳过 apt（依赖已自行装好）
#
# 作者: laolibuhuifei   https://github.com/laolibuhuifei/netease-music-cli

set -e

APP_NAME="netease-music-cli"
SKIP_APT=0
[ "$1" = "--no-apt" ] && SKIP_APT=1

cd "$(dirname "$(readlink -f "$0")")"

echo "=============================================="
echo " $APP_NAME 安装脚本"
echo " 作者: laolibuhuifei"
echo "=============================================="
echo

# ---- 1. 环境检查 ----
echo "--- 1/5 环境检查 ---"
ARCH=$(uname -m)
echo " 架构: $ARCH"
case "$ARCH" in
    armv6l|armv7l|aarch64) echo " 看起来是树莓派/ARM 设备，继续" ;;
    *) echo " [提示] 非 ARM 设备，理论可用但未实测" ;;
esac

if ! command -v python3 >/dev/null; then
    echo " [错误] 未找到 python3"
    exit 1
fi
PY_VER=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
echo " Python: $PY_VER"
python3 -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null || {
    echo " [错误] 需要 Python 3.9 及以上"; exit 1; }

# ---- 2. 系统依赖 ----
echo
echo "--- 2/5 系统依赖 ---"
if [ "$SKIP_APT" -eq 1 ]; then
    echo " 已跳过（--no-apt）"
else
    sudo apt update -qq
    # pycryptodome 在 Debian 上叫 python3-pycryptodome，命名空间是 Cryptodome
    sudo apt install -y -qq mpv python3 python3-pip \
        python3-requests python3-rich python3-pycryptodome
fi

command -v mpv >/dev/null || { echo " [错误] mpv 未安装"; exit 1; }
echo " mpv: $(mpv --version | head -1)"

# ---- 3. Python 依赖自检 ----
echo
echo "--- 3/5 Python 依赖自检 ---"
python3 - <<'PY'
import importlib.util
for pkg, mod in (("requests", "requests"), ("rich", "rich")):
    print(f"  {mod:12s}: {'OK' if importlib.util.find_spec(mod) else '缺失'}")
crypto = [m for m in ("Crypto", "Cryptodome") if importlib.util.find_spec(m)]
print(f"  pycryptodome: {crypto[0] if crypto else '缺失'}")
PY

# ---- 4. 数据目录 ----
echo
echo "--- 4/5 数据目录 ---"
mkdir -p .config .cache/covers .cache/lyrics .cache/songs
echo " 已创建 .config / .cache"

# ---- 5. 安装命令 ----
echo
echo "--- 5/5 安装命令 ---"
chmod +x "$APP_NAME" install.sh
sudo ln -sf "$PWD/$APP_NAME" "/usr/local/bin/$APP_NAME"
# 短命令别名，方便手敲
sudo ln -sf "$PWD/$APP_NAME" /usr/local/bin/netease
echo " 已安装: /usr/local/bin/$APP_NAME"
echo " 已别名: /usr/local/bin/netease"

# ---- 音频提示 ----
echo
echo "--- 音频设备检查 ---"
if command -v aplay >/dev/null; then
    CARDS=$(aplay -l 2>/dev/null | grep -c '^card' || true)
    if [ "$CARDS" -eq 0 ]; then
        echo " [警告] 未检测到声卡。树莓派默认可能关闭了模拟音频，"
        echo "        见 README「让树莓派有声卡」一节。"
    else
        aplay -l 2>/dev/null | grep '^card' | sed 's/^/ /'
    fi
fi

# ---- 完成 ----
echo
echo "=============================================="
echo " 安装完成"
echo "=============================================="
"$APP_NAME" --version
echo
echo "下一步："
echo "  $APP_NAME login          # 扫码登录（二维码直接画在终端里）"
echo "  $APP_NAME                # 交互模式"
echo "  $APP_NAME search 晴天     # 直接搜索"
echo
echo "文档: https://github.com/laolibuhuifei/netease-music-cli"
