"""登录模块：二维码登录 + 手机号登录。

二维码登录流程：
1. 调用 API 生成 unikey
2. 生成二维码（终端显示）
3. 轮询检查扫码状态
4. 登录成功后保存 MUSIC_U cookie
"""

import time

from api.client import NeteaseAPI
from config import load_config, save_config


class LoginManager:
    """登录管理器。"""

    def __init__(self, api: NeteaseAPI):
        self.api = api

    def qrcode_login(self) -> bool:
        """二维码登录流程。

        在终端上显示二维码，等待用户扫码。

        Returns:
            登录是否成功
        """
        # 1. 获取 unikey
        resp = self.api.qrcode_create()
        if resp.get("code") != 200 or "unikey" not in resp:
            print(f"[错误] 获取二维码 key 失败: {resp}")
            return False

        unikey = resp["unikey"]

        # 2. 生成二维码 URL 并显示
        qr_url = f"https://music.163.com/login?codekey={unikey}"
        self._display_qrcode(qr_url)

        print("等待扫码中... (超时 120 秒)\n")

        # 3. 轮询检查状态
        start_time = time.time()
        timeout = 120

        while time.time() - start_time < timeout:
            resp = self.api.qrcode_check(unikey)
            code = resp.get("code")

            if code == 800:
                print("[错误] 二维码已过期，请重试")
                return False
            elif code == 801:
                # 等待扫码
                elapsed = int(time.time() - start_time)
                print(f"\r等待扫码... ({elapsed}s)", end="", flush=True)
            elif code == 802:
                # 已扫码，待确认
                nickname = resp.get("nickname", "")
                print(f"\r已扫码: {nickname}，请在手机上确认登录    ")
            elif code == 803:
                # 登录成功
                print("\n登录成功！")
                # 提取 MUSIC_U
                music_u = ""
                for cookie in self.api.session.cookies:
                    if cookie.name == "MUSIC_U":
                        music_u = cookie.value
                        break

                if not music_u:
                    print("[警告] 未找到 MUSIC_U cookie")
                    return False

                # 保存到配置
                cfg = load_config()
                cfg["music_u"] = music_u
                # 构建完整 cookie 字符串
                cookie_str = "; ".join(
                    f"{c.name}={c.value}" for c in self.api.session.cookies
                )
                cfg["cookie"] = cookie_str
                save_config(cfg)

                # 获取用户信息
                user_info = self.api.user_account()
                if user_info.get("code") == 200:
                    account = user_info.get("account", {})
                    profile = user_info.get("profile", {})
                    nickname = profile.get("nickname", "未知")
                    uid = account.get("id", 0)
                    print(f"用户: {nickname} (UID: {uid})")

                return True

            time.sleep(2)

        print("\n[超时] 二维码登录超时")
        return False

    def _display_qrcode(self, url: str) -> bool:
        """在终端里直接画出二维码，并始终附上原始链接。

        二维码由 auth.qrterm 用纯 Python 生成，不依赖 qrcode 库、
        qrencode 命令或浏览器——低性能设备上刷网页很吃力，
        但终端画二维码几乎不占资源。

        Returns:
            是否成功画出了二维码
        """
        print()
        drawn = False
        try:
            from auth.qrterm import terminal_qr
            drawn = terminal_qr(url)
        except Exception as exc:            # pragma: no cover - 兜底
            print(f"[提示] 终端二维码渲染失败：{exc}")

        if not drawn:
            # 第二选择：系统里恰好装了 qrencode
            try:
                import subprocess
                subprocess.run(["qrencode", "-t", "ANSIutf8", url], check=True)
                drawn = True
            except (FileNotFoundError, subprocess.CalledProcessError, OSError):
                drawn = False

        print()
        if drawn:
            print("  用「网易云音乐」App 扫上方二维码")
        print(f"  二维码链接: {url}")
        if drawn:
            print("  扫不了码？把上面的链接复制到手机上打开也能登录")
        else:
            print("  请把上面的链接转成二维码后扫码，或在手机浏览器打开")
        return drawn

    def phone_login(self, phone: str, password: str = "") -> bool:
        """手机号登录。

        Args:
            phone: 手机号
            password: 明文密码（API 内部会 MD5）

        Returns:
            登录是否成功
        """
        resp = self.api.login_cellphone(phone, password)
        if resp.get("code") == 200:
            # 提取 MUSIC_U
            music_u = ""
            for cookie in self.api.session.cookies:
                if cookie.name == "MUSIC_U":
                    music_u = cookie.value
                    break

            if music_u:
                cfg = load_config()
                cfg["music_u"] = music_u
                cookie_str = "; ".join(
                    f"{c.name}={c.value}" for c in self.api.session.cookies
                )
                cfg["cookie"] = cookie_str
                save_config(cfg)
                print("登录成功！")
                return True
            else:
                print("[警告] 登录返回成功但未获取到 MUSIC_U")
                return False
        elif resp.get("code") == 200:
            print("登录成功")
            return True
        else:
            print(f"登录失败: {resp}")
            return False

    def check_login(self) -> bool:
        """检查是否已登录（cookie 是否有效）。"""
        resp = self.api.login_status()
        if resp.get("code") == 200 and resp.get("account"):
            return True
        return False

    def logout(self):
        """退出登录，清除保存的 cookie。"""
        cfg = load_config()
        cfg["music_u"] = ""
        cfg["cookie"] = ""
        save_config(cfg)
        print("已退出登录")
