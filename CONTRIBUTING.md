# 贡献指南

感谢有兴趣改进这个项目。下面是一些实用的约定，能省下不少来回。

## 开发环境

```bash
git clone https://github.com/laolibuhuifei/netease-music-cli.git
cd netease-music-cli

# 系统依赖
sudo apt install -y mpv python3-requests python3-rich python3-pycryptodome

# 代码风格工具
pip install ruff
```

不需要装 `qrcode` / `qrencode` —— 二维码是纯 Python 实现的。

## 提交前请确认

```bash
ruff check .                              # 代码风格
python3 -m unittest discover -s tests -v  # 单元测试
python3 -m compileall -q api auth cache player ui main.py config.py
```

如果想验证界面，建议在真实 pty 里跑：

```bash
python3 tests/test_tui_keys.py
```

## 不要提交的东西

`.gitignore` 已经排除了，但提 PR 时还是留意一下：

- `.config/` —— **里面存着登录 cookie（`MUSIC_U`），泄露等于账号被人用**
- `.cache/` —— 歌词、封面等运行时缓存
- 任何内网 IP、主机名、SSH 密码

## 代码约定

- 注释和用户可见文案用中文，变量名 / 函数名用英文
- 新增依赖前先想想：这台设备只有 512MB 内存，能不加就不加
- 涉及终端渲染的改动，务必在**真实 pty** 里验证，不要只看输出字符串
- 用 `subprocess` 调外部命令时，注意 `pkill -f` 这类命令会匹配到自己所在的 shell

## 调试终端问题的小技巧

界面类问题（空白、错位、闪烁）光看代码很难判断，建议这样取证：

```bash
# 把程序真正写出去的字节录下来
script -q -c "python3 main.py" /tmp/cap.txt

# 看有多少字节、有没有进入备用屏幕
python3 -c "
d=open('/tmp/cap.txt','rb').read()
print(len(d), b'\x1b[?1049h' in d)
"
```

如果在没有 tty 的环境里测试 `pty.fork()`，记得手动设置窗口尺寸，
否则 pty 默认是 0×0，rich 会一个字都不画：

```python
import fcntl, struct, termios
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
```

## 提交信息

用中文或英文都可以，建议带前缀：

```
feat: 支持逐字歌词
fix: 修复 OPOST 被关闭导致的整屏空白
docs: 补充树莓派声卡配置
refactor: 拆分 TUI 渲染逻辑
```

## 提 PR

- 一个 PR 解决一件事，别把重构和功能混在一起
- 说明**为什么改**，而不只是改了什么
- 涉及界面变化的，附一张终端截图或录屏
- CI 必须绿

## 接口变更

本项目依赖逆向得到的网易云接口，接口随时可能变。如果你发现某个功能突然
失效，先用诊断脚本确认是接口问题还是本地问题：

```bash
python3 tools/verify_deploy.py
```
