"""项目元信息。

名称、版本、作者集中在这里，改名字只需要改这个文件。
"""

APP_NAME = "netease-music-cli"
APP_VERSION = "0.1.0"
APP_AUTHOR = "laolibuhuifei"
APP_REPO = "https://github.com/laolibuhuifei/netease-music-cli"
APP_DESC = "为树莓派等低性能设备打造的网易云音乐命令行客户端"
APP_LICENSE = "MIT"


def version_line() -> str:
    """例：netease-music-cli v0.1.0"""
    return f"{APP_NAME} v{APP_VERSION}"


def author_line() -> str:
    """例：by laolibuhuifei  https://github.com/laolibuhuifei/netease-music-cli"""
    return f"by {APP_AUTHOR}  {APP_REPO}"


def banner_lines() -> list:
    """终端横幅，用于 help / version / 退出提示。"""
    return [
        f"{APP_NAME} v{APP_VERSION}",
        f"{APP_DESC}",
        f"作者: {APP_AUTHOR}",
        f"仓库: {APP_REPO}",
        f"许可证: {APP_LICENSE}",
    ]
