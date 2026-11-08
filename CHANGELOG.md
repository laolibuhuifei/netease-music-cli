# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-11-08

首个公开版本。在 Raspberry Pi Zero 2W（Raspbian 12 / armv7l / 425MB 可用内存）
上完成全链路实测。

### 命名与信息

- 程序名统一为 `netease-music-cli`，命令同时提供短别名 `netease`
- 新增 `about.py` 集中管理名称 / 版本 / 作者，改名字只需改一处
- 新增 `--version` / `-V`，输出名称、版本、作者、仓库、许可证
- `--help`、`diag`、退出提示、`install.sh`、部署验证脚本均带作者信息
- 作者：laolibuhuifei · 许可证：MIT

### 功能

- 终端交互界面（rich + 备用屏幕），支持播放/暂停、上下曲、进度、音量、
  顺序/单曲循环/随机三种模式
- 搜索、我的歌单、每日推荐、歌词显示
- 播放队列管理，不可播放歌曲自动跳过并提示原因
- 扫码登录 / 手机号登录
- **登录二维码直接在终端内绘制**，零第三方依赖（`auth/qrterm.py`）
- SQLite 缓存歌词、歌曲信息、搜索历史
- 非交互环境自动降级为纯文本模式

### 技术要点

- 实现 weapi 加密（AES-128-CBC 两轮 + RSA 1024），兼容 `Crypto` / `Cryptodome`
  两种 pycryptodome 命名空间
- 通过 mpv IPC socket 控制播放，`--idle` 常驻
- 纯 Python 二维码编码器：byte 模式 + 纠错等级 L + 版本 1~10 + 8 种掩码择优
- 终端 raw 模式手写 termios（不用 `tty.setraw()`，避免 `TCSAFLUSH` 吞按键）

### 修复过的问题

- 搜索接口：旧版 `/search/get/web` 可匿名调用，`/cloudsearch/get/web` 会返回 50000005
- 歌曲 URL 接口：`/song/enhance/player/url` 传 `br` 整数，`/song/url/v1` 返回 404
- mpv 音频设备写成 `default` 会导致播放进度卡在 0 秒（必须用 `auto`）
- 树莓派内核参数默认关闭模拟音频，需手动开启 `snd_bcm2835`
- **界面全黑**：raw 模式误关 `OPOST`，导致 `\n` 不回行首，整屏错位并滚出可视区
- 终端尺寸上报 0×0 时 rich 拒绝渲染，已兜底 80×24
- `⏹`(U+23F9) / `⏸`(U+23F8) 在树莓派默认字体中缺失，改用 `■` / `‖`
- 界面闪烁：改为备用屏幕 + 内容脏检查，实测播放时 1.0 次/秒、空闲 0 次

### 验证

- 二维码矩阵与参考实现 `qrcode` 库在版本 1~10 × 8 种掩码下共 240 组逐位一致
- 终端渲染结果用独立解码器 `zxing-cpp` 反解，可正确还原登录 URL
- 端到端测试：按键响应、ESC 取消、中文输入搜索、重绘频率

[0.1.0]: https://github.com/laolibuhuifei/netease-music-cli/releases/tag/v0.1.0
