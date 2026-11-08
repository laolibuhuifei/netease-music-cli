#!/bin/bash
# Raspi-Netease CLI 安装脚本
# 在树莓派上运行此脚本完成安装

set -e

echo "=== Raspi-Netease CLI 安装脚本 ==="

# 检查是否为树莓派
if ! uname -m | grep -q "arm\|aarch"; then
    echo "[警告] 当前系统可能不是树莓派，继续安装..."
fi

# 安装系统依赖
echo ""
echo "--- 安装系统依赖 ---"
sudo apt update -qq
sudo apt install -y -qq mpv python3 python3-pip

# 检查 mpv
if command -v mpv &>/dev/null; then
    echo "[OK] mpv 已安装: $(mpv --version | head -1)"
else
    echo "[错误] mpv 安装失败"
    exit 1
fi

# 安装 Python 依赖
echo ""
echo "--- 安装 Python 依赖 ---"
pip3 install --user -r requirements.txt

# 检查音频设备
echo ""
echo "--- 检查音频设备 ---"
if command -v aplay &>/dev/null; then
    echo "可用音频设备:"
    aplay -l 2>/dev/null | grep "^card" || echo "  (未检测到 ALSA 设备，可能需要配置)"
fi

# 创建必要目录
echo ""
echo "--- 创建目录 ---"
mkdir -p .config .cache/covers .cache/lyrics .cache/songs

# 检查网络
echo ""
echo "--- 检查网络连接 ---"
if ping -c 1 -W 3 music.163.com &>/dev/null; then
    echo "[OK] 网易云音乐服务可达"
else
    echo "[警告] 无法连接 music.163.com，请检查网络"
fi

echo ""
echo "=== 安装完成 ==="
echo "使用方法:"
echo "  python3 main.py login      # 扫码登录"
echo "  python3 main.py search 晴天  # 搜索歌曲"
echo "  python3 main.py              # 交互模式"
echo ""
echo "提示: 如果音频没有声音，请检查 ALSA 配置"
echo "  sudo raspi-config  # 选择 Audio 输出设备"
