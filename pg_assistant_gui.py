import asyncio
import hashlib
import random
import sys
import time
import os
import json
import threading
import requests
from typing import Final, List, Dict, Tuple, Optional, Union
from urllib.parse import urlparse
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter.constants import END, DISABLED, NORMAL
from apscheduler.schedulers.background import BackgroundScheduler

# -------------------------- 依赖自动安装（仅首次运行） --------------------------
try:
    import httpx
    from loguru import logger
    import apscheduler
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "loguru", "requests", "apscheduler"])
    import httpx
    from loguru import logger
    from apscheduler.schedulers.background import BackgroundScheduler

# -------------------------- 核心常量/类 --------------------------
TOKEN_FILE_PATH: Final[str] = "token.txt"
CONFIG_FILE_PATH: Final[str] = "config.txt"
APP_VERSION: Final[str] = "1.82.1"
APP_SECRET: Final[str] = "nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o="
ALIPAY_APP_SECRET: Final[str] = "Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY="
PHONE_TOKEN_FILE: Final[str] = "phone_tokens.json"
AUTO_CONFIG_FILE: Final[str] = "auto_config.json"  # 自动化配置文件

TASKS: Final[List[str]] = [
    "bd28f4af-44d6-4920-8e34-51b42a07960c", "c48ebae8-4c11-490e-8ec0-570053dcb020",
    "90a0dceb-8b89-4c5a-b08d-60cf43b9a0c8", "02388d14-3ab5-43fc-b709-108b371fb6d8",
    "d798d2e3-7c16-4b5d-9e6d-4b8214ebf2e5", "7", "c6fee3bc-84ba-4090-9303-2fbf207b2bbd", "5", "2"
]
ALIPAY_TASKS: Final[List[str]] = ["9"]

class RunMode:
    FULL = 1
    NO_APP_TASKS = 2
    ONLY_CHECKIN = 3

@dataclass
class AccountConfig:
    token: str
    phone_brand: str = "Android"
    enabled: bool = True
    delay_min: int = 0
    delay_max: int = 0

class PgAccount:
    def __init__(self, token: str, phone_brand: str):
        self.client = httpx.AsyncClient(
            base_url="https://userapi.qiekj.com",
            event_hooks={"request": [self._request_hook]},
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self.token = token
        self.phone_brand = phone_brand
        self.username: Optional[str] = None

    @classmethod
    async def create(cls, token: str, phone_brand: str):
        self = cls(token, phone_brand)
        await self._get_acw_tc()
        self.username = await self.get_user_name()
        return self

    def get_sign(self, request_url: Union[str, httpx.URL], timestamp: Union[str, int], channel="android_app") -> str:
        parsed_url = urlparse(str(request_url))
        path = parsed_url.path
        if channel.lower() == "android_app":
            signature_string = f"appSecret={APP_SECRET}&channel={channel}&timestamp={str(timestamp)}&token={self.token}&version={APP_VERSION}&{path}"
        elif channel.lower() == "alipay":
            signature_string = f"appSecret={ALIPAY_APP_SECRET}&channel={channel.lower()}&timestamp={str(timestamp)}&token={self.token}&{path}"
        else:
            raise ValueError(f"Unknown channel: {channel}")
        return hashlib.sha256(signature_string.encode("utf-8")).hexdigest()

    async def get_balance(self) -> Dict:
        try:
            _data = {"token": self.token}
            response = await self.client.post("/user/balance", data=_data)
            response.raise_for_status()
            response_json = response.json()
            if response_json.get("code") != 0:
                raise Exception(f"API返回错误: {response_json.get('message')}")
            return response_json["data"]
        except httpx.RequestError as e:
            raise Exception(f"网络请求失败: {e}")
        except KeyError as e:
            raise Exception(f"解析响应失败: {e}")

    async def _get_acw_tc(self):
        try:
            _data = {"slotKey": "android_open_screen_1_35_0", "token": self.token}
            response = await self.client.post("/slot/get", data=_data)
            response.raise_for_status()
            return response.headers.get("Set-Cookie", "").split(";")[0]
        except Exception as e:
            logger.warning(f"获取acw_tc失败: {e}")
            return ""

    async def _request_hook(self, request: httpx.Request):
        timestamp = str(int(time.time() * 1000))
        request.headers.update({
            "User-Agent": "okhttp/4.12.0",
            "Accept-Encoding": "gzip",
            "Version": APP_VERSION,
            "phoneBrand": self.phone_brand,
            "Authorization": self.token,
            "timestamp": timestamp,
        })
        channel = request.extensions.get("channel", "android_app")
        if channel == "alipay":
            request.headers["sign"] = self.get_sign(request.url, timestamp, "alipay")
            request.headers["channel"] = "alipay"
            request.headers.pop("Version", None)
            request.headers.pop("phoneBrand", None)
        else:
            request.headers["sign"] = self.get_sign(request.url, timestamp)
            request.headers["channel"] = "android_app"

    async def complete_task(self, task_code: str, channel="android_app") -> bool:
        try:
            _data = {"taskCode": task_code, "token": self.token}
            response = await self.client.post(
                url="/task/completed", data=_data, extensions={"channel": channel}
            )
            response.raise_for_status()
            response_json = response.json()
            return response_json.get("code") == 0 and response_json.get("data") is True
        except Exception as e:
            logger.error(f"完成任务失败: {e}")
            return False

    async def is_captcha(self) -> bool:
        try:
            _data = {"token": self.token}
            response = await self.client.post(url="/integralCaptcha/isCaptcha", data=_data)
            response.raise_for_status()
            return False
        except Exception as e:
            if "人机验证" in str(e):
                return True
            return False

    async def get_task_list(self, channel="android_app") -> List[Dict]:
        try:
            _data = {"token": self.token}
            response = await self.client.post(
                url="/task/list", data=_data, extensions={"channel": channel}
            )
            response.raise_for_status()
            response_json = response.json()
            if response_json.get("code") != 0:
                raise Exception(f"获取任务列表失败: {response_json.get('message')}")
            return response_json["data"]["items"]
        except Exception as e:
            logger.error(f"获取任务列表失败: {e}")
            return []

    async def checkin(self) -> bool:
        try:
            _data = {"activityId": "600001", "token": self.token}
            response = await self.client.post(url="/signin/doUserSignIn", data=_data)
            response.raise_for_status()
            response_json = response.json()
            if response_json.get("code") == 0:
                return True
            else:
                logger.warning(f"签到失败: {response_json.get('message')}")
                return False
        except Exception as e:
            logger.error(f"签到请求失败: {e}")
            return False

    async def get_user_name(self) -> str:
        try:
            data = {"token": self.token}
            response = await self.client.post("/user/info", data=data)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("code") != 0:
                return "未知用户"
            user_name = res_json["data"].get("userName")
            return user_name if user_name else "未设置昵称"
        except Exception:
            return "未知用户"

# -------------------------- token相关函数 --------------------------
def sha256_encrypt(data):
    sha256 = hashlib.sha256()
    sha256.update(data.encode("utf-8"))
    return sha256.hexdigest()

def sign_token(t, url, data_str=""):
    base_str = f"appSecret=nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o=&channel=android_app&timestamp={t}&version=1.60.3&{data_str}"
    return sha256_encrypt(base_str)

def load_phone_tokens() -> Dict[str, str]:
    if not os.path.exists(PHONE_TOKEN_FILE):
        return {}
    try:
        with open(PHONE_TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("phone_tokens.json格式错误，将重新创建")
        return {}

def save_phone_token(phone: str, token: str):
    tokens = load_phone_tokens()
    tokens[phone] = token
    with open(PHONE_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存手机号 {phone} 的token")

def get_token_fixed(phone: str) -> Optional[str]:
    logger.info(f"开始为手机号 {phone} 获取token...")
    send_code_url = "https://userapi.qiekj.com/common/sms/sendCode"
    t = str(int(time.time() * 1000))
    headers = {
        "Version": "1.60.3",
        "channel": "android_app",
        "phoneBrand": "Redmi",
        "timestamp": t,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Host": "userapi.qiekj.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; Redmi Note 11 Pro Build/SKQ1.211006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/100.0.4896.58 Mobile Safari/537.36",
    }
    data = {"phone": phone, "template": "reg"}

    try:
        logger.info("发送验证码请求...")
        response = requests.post(send_code_url, headers=headers, data=data, timeout=10)
        result = response.json()
        logger.info(f"发送验证码响应: {result}")

        if result.get("code") == 0:
            verify_code = None
            def on_confirm():
                nonlocal verify_code
                verify_code = code_entry.get()
                code_win.destroy()
            code_win = tk.Toplevel()
            code_win.title("输入验证码")
            code_win.geometry("300x150")
            code_win.resizable(False, False)
            tk.Label(code_win, text=f"验证码已发送至 {phone}", font=("微软雅黑", 10)).pack(pady=10)
            code_entry = ttk.Entry(code_win, width=20)
            code_entry.pack(pady=5)
            ttk.Button(code_win, text="确认", command=on_confirm).pack(pady=10)
            code_win.wait_window()

            if not verify_code:
                logger.error("未输入验证码")
                return None

            reg_url = "https://userapi.qiekj.com/user/reg"
            reg_data = {"channel": "android_app", "phone": phone, "verify": verify_code}
            t2 = str(int(time.time() * 1000))
            headers["timestamp"] = t2
            logger.info("提交验证码注册...")
            reg_response = requests.post(reg_url, headers=headers, data=reg_data, timeout=10)
            reg_result = reg_response.json()
            logger.info(f"注册响应: {reg_result}")

            if reg_result.get("code") == 0 and "data" in reg_result and "token" in reg_result["data"]:
                token = reg_result["data"]["token"]
                logger.success(f"成功获取token: {token}")
                save_phone_token(phone, token)
                with open(TOKEN_FILE_PATH, "w", encoding="utf-8") as f:
                    f.write(token)
                logger.info(f"token已保存到 {TOKEN_FILE_PATH}")
                return token
            else:
                logger.error(f"注册失败: {reg_result.get('msg', '未知错误')}")
                return None
        else:
            error_msg = result.get("msg", "未知错误")
            logger.error(f"发送验证码失败: {error_msg}")
            if result.get("code") == 40001:
                logger.warning("请求过于频繁，请等待几分钟再试")
            elif result.get("code") == 40002:
                logger.warning("手机号格式错误")
            elif result.get("code") == 40003:
                logger.warning("该手机号已注册（可尝试手动输入token）")
            return None
    except requests.exceptions.Timeout:
        logger.error("请求超时，请检查网络连接")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("网络连接错误，请检查网络")
        return None
    except Exception as e:
        logger.error(f"获取token未知错误: {e}")
        return None

# -------------------------- GUI核心逻辑 --------------------------
class PgAssistantGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("胖乖积分助手")
        self.root.geometry("800x600")
        self.root.resizable(False, False)
        self.current_token = ""
        self.task_thread = None
        
        # 用auto_window标记自动化窗口状态（None=未打开，实例=已打开）
        self.auto_window = None
        self.status_label = None  # 状态标签
        
        # 自动化调度器
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        
        # 关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 标题区
        self.title_label = tk.Label(
            root, text="胖乖积分助手", font=("微软雅黑", 24, "bold"), fg="#2c3e50"
        )
        self.title_label.pack(pady=20)

        # 手机号输入区
        self.input_frame = ttk.Frame(root)
        self.input_frame.pack(pady=10, fill=tk.X, padx=50)

        self.phone_label = ttk.Label(self.input_frame, text="手机号:", font=("微软雅黑", 12))
        self.phone_label.pack(side=tk.LEFT, padx=5)

        self.phone_entry = ttk.Entry(self.input_frame, width=20, font=("微软雅黑", 12))
        self.phone_entry.pack(side=tk.LEFT, padx=5)

        self.phone_combobox = ttk.Combobox(
            self.input_frame, width=18, font=("微软雅黑", 12), state="readonly"
        )
        self.load_phone_combobox()
        self.phone_combobox.bind("<<ComboboxSelected>>", self.on_phone_selected)
        self.phone_combobox.pack(side=tk.LEFT, padx=5)

        self.get_token_btn = ttk.Button(
            self.input_frame, text="获取新token", command=self.on_get_token_click
        )
        self.get_token_btn.pack(side=tk.LEFT, padx=5)

        # 设置按钮
        self.settings_btn = ttk.Button(
            self.input_frame, text="设置", command=self.open_settings_window
        )
        self.settings_btn.pack(side=tk.RIGHT, padx=5)

        # 功能按钮区
        self.btn_frame = ttk.Frame(root)
        self.btn_frame.pack(pady=15)

        self.main_btn = ttk.Button(
            self.btn_frame, text="选择执行模式", command=self.toggle_sub_buttons
        )
        self.main_btn.pack()

        self.sub_btn_frame = ttk.Frame(self.btn_frame)
        self.sub_buttons_visible = False

        self.sub_btns = [
            ttk.Button(
                self.sub_btn_frame, text="1. 全自动化（所有任务）", command=lambda: self.run_task(RunMode.FULL)
            ),
            ttk.Button(
                self.sub_btn_frame, text="2. 禁用APP任务（仅签到+小程序）", command=lambda: self.run_task(RunMode.NO_APP_TASKS)
            ),
            ttk.Button(
                self.sub_btn_frame, text="3. 仅运行签到任务", command=lambda: self.run_task(RunMode.ONLY_CHECKIN)
            )
        ]

        # 日志显示区
        self.log_label = ttk.Label(root, text="执行日志:", font=("微软雅黑", 12))
        self.log_label.pack(pady=5)

        self.log_text = scrolledtext.ScrolledText(
            root, width=95, height=25, font=("Consolas", 10), state=DISABLED
        )
        self.log_text.pack(padx=20, pady=5)

        # 日志重定向
        self.setup_log_redirect()

    def load_phone_combobox(self):
        phone_tokens = load_phone_tokens()
        phones = list(phone_tokens.keys())
        self.phone_combobox["values"] = phones
        if phones:
            self.phone_combobox.current(0)
            self.current_token = phone_tokens[phones[0]]

    def on_phone_selected(self, event):
        selected_phone = self.phone_combobox.get()
        phone_tokens = load_phone_tokens()
        if selected_phone in phone_tokens:
            self.current_token = phone_tokens[selected_phone]
            self.phone_entry.delete(0, END)
            self.phone_entry.insert(0, selected_phone)
            logger.info(f"已选择手机号 {selected_phone}，token已加载")

    def toggle_sub_buttons(self):
        if self.sub_buttons_visible:
            self.sub_btn_frame.pack_forget()
            self.main_btn.config(text="选择执行模式")
        else:
            for btn in self.sub_btns:
                btn.pack(side=tk.LEFT, padx=10, pady=5)
            self.sub_btn_frame.pack(pady=10)
            self.main_btn.config(text="收起选项")
        self.sub_buttons_visible = not self.sub_buttons_visible

    def on_get_token_click(self):
        phone = self.phone_entry.get().strip()
        if not phone or len(phone) != 11 or not phone.isdigit():
            messagebox.showerror("错误", "请输入正确的11位手机号！")
            return
        threading.Thread(target=self._get_token_thread, args=(phone,), daemon=True).start()

    def _get_token_thread(self, phone: str):
        token = get_token_fixed(phone)
        if token:
            self.current_token = token
            self.load_phone_combobox()
            messagebox.showinfo("成功", f"手机号 {phone} 的token获取成功！")
        else:
            messagebox.showerror("失败", "token获取失败，请查看日志！")

    def run_task(self, run_mode: int):
        if not self.current_token:
            messagebox.showerror("错误", "未选择或获取token，请先操作！")
            return
        if self.task_thread and self.task_thread.is_alive():
            messagebox.showwarning("提示", "已有任务在执行中，请等待完成！")
            return
        self.task_thread = threading.Thread(
            target=self._run_task_thread, args=(run_mode,), daemon=True
        )
        self.task_thread.start()

    def _run_task_thread(self, run_mode: int):
        try:
            account_config = AccountConfig(token=self.current_token)
            asyncio.run(self.process_single_account(account_config, run_mode))
            logger.success("所有任务执行完成！")
        except Exception as e:
            logger.error(f"任务执行异常: {e}")

    async def process_single_account(self, account_config: AccountConfig, run_mode: int):
        if not account_config.enabled:
            logger.info("账号已禁用，跳过处理")
            return
        if account_config.delay_max > account_config.delay_min:
            delay = random.randint(account_config.delay_min, account_config.delay_max)
            logger.info(f"随机延迟 {delay} 秒后开始处理")
            await asyncio.sleep(delay)
        try:
            account = await PgAccount.create(account_config.token, account_config.phone_brand)
            logger.info(f"开始处理账号: {account.username}（模式: {self.get_mode_name(run_mode)}）")
            try:
                balance_dict = await account.get_balance()
                logger.info(f"当前通用小票: {int(balance_dict['tokenCoin']) / 100}")
                logger.info(f"当前积分: {balance_dict['integral']}")
            except Exception as e:
                logger.warning(f"获取余额失败: {e}")
            await self.process_checkin(account)
            if run_mode == RunMode.FULL:
                await self.process_app_tasks(account)
                await self.process_miniprogram_tasks(account)
            elif run_mode == RunMode.NO_APP_TASKS:
                await self.process_miniprogram_tasks(account)
            elif run_mode == RunMode.ONLY_CHECKIN:
                logger.info("仅签到模式，跳过所有任务")
            try:
                balance_dict = await account.get_balance()
                logger.success(f"任务完成，当前积分: {balance_dict['integral']}")
            except Exception as e:
                logger.warning(f"获取最终余额失败: {e}")
        except Exception as e:
            logger.error(f"处理账号时发生错误: {e}")
        finally:
            if 'account' in locals():
                await account.client.aclose()

    async def process_checkin(self, account: PgAccount):
        logger.info("尝试签到")
        if await self.handle_captcha(account, "签到"):
            await asyncio.sleep(random.random())
            if await account.checkin():
                logger.success("签到成功")
            else:
                logger.error("签到失败")
        else:
            logger.error("无法绕过人机验证，跳过签到")

    async def process_app_tasks(self, account: PgAccount):
        logger.info("开始胖乖生活APP任务")
        tasks = await account.get_task_list()
        if not tasks:
            logger.warning("未获取到APP任务列表")
            return
        await self.process_tasks(account, tasks, TASKS, "android_app")
        logger.info("胖乖生活APP任务结束")

    async def process_miniprogram_tasks(self, account: PgAccount):
        logger.info("开始胖乖生活小程序任务")
        tasks = await account.get_task_list(channel="alipay")
        if not tasks:
            logger.warning("未获取到小程序任务列表")
            return
        await self.process_tasks(account, tasks, ALIPAY_TASKS, "alipay")
        logger.info("胖乖生活小程序任务结束")

    async def process_tasks(self, account: PgAccount, tasks: List[Dict], target_tasks: List[str], channel: str):
        for task in tasks:
            if (task["taskCode"] in target_tasks and 
                task["completedStatus"] == 0 and 
                task["completedFreq"] is not None):
                remaining_times = task["dailyTaskLimit"] - task["completedFreq"]
                if remaining_times <= 0:
                    continue
                logger.info(f"开始处理任务: {task['title']}（剩余{remaining_times}次）")
                for num in range(1, remaining_times + 1):
                    logger.info(f"尝试完成第 {num} 次 {task['title']}")
                    if await self.handle_captcha(account, f"任务{num}"):
                        await asyncio.sleep(random.randint(45, 55))
                        if await account.complete_task(task["taskCode"], channel):
                            logger.success(f"成功完成第 {num} 次 {task['title']}")
                            await asyncio.sleep(random.randint(35, 95))
                        else:
                            logger.error(f"完成第 {num} 次 {task['title']} 失败")
                            break
                    else:
                        logger.error(f"无法绕过人机验证，跳过任务 {task['title']}")
                        break

    async def handle_captcha(self, account: PgAccount, operation: str) -> bool:
        for i in range(1, 4):
            try:
                if await account.is_captcha():
                    if i == 3:
                        logger.error(f"{operation} - 无法绕过人机验证")
                        return False
                    logger.warning(f"{operation} - 触发人机验证，第 {i} 次重试")
                    await asyncio.sleep(random.randint(65, 125))
                else:
                    return True
            except Exception as e:
                logger.warning(f"{operation} - 检查验证时出错: {e}")
                await asyncio.sleep(random.randint(65, 125))
        return False

    def get_mode_name(self, run_mode: int) -> str:
        mode_names = {
            RunMode.FULL: "全自动化",
            RunMode.NO_APP_TASKS: "禁用APP任务",
            RunMode.ONLY_CHECKIN: "仅签到"
        }
        return mode_names.get(run_mode, "未知模式")

    def setup_log_redirect(self):
        """重定向日志到文本框"""
        global print
        original_print = print
        def new_print(*args, **kwargs):
            original_print(*args, **kwargs)
            msg = " ".join(map(str, args)) + "\n"
            self.log_text.config(state=NORMAL)
            self.log_text.insert(END, msg)
            self.log_text.see(END)
            self.log_text.config(state=DISABLED)
        print = new_print

        class TextHandler:
            def __init__(self, text_widget):
                self.text_widget = text_widget
            def write(self, msg):
                if msg.strip():
                    self.text_widget.config(state=NORMAL)
                    self.text_widget.insert(END, msg)
                    self.text_widget.see(END)
                    self.text_widget.config(state=DISABLED)
            def flush(self):
                pass

        text_handler = TextHandler(self.log_text)
        logger.remove()
        logger.add(
            text_handler,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>\n",
            level="INFO"
        )

    def open_settings_window(self):
        """打开设置窗口"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("400x300")
        settings_window.resizable(False, False)
        
        title_label = tk.Label(
            settings_window, 
            text="第四季SeasonVI", 
            font=("微软雅黑", 20, "bold"), 
            fg="#2c3e50"
        )
        title_label.pack(pady=30)
        
        btn_frame = ttk.Frame(settings_window)
        btn_frame.pack(pady=20)
        
        about_btn = ttk.Button(
            btn_frame, 
            text="关于作者", 
            command=self.show_author_info
        )
        about_btn.pack(pady=10, padx=20, fill=tk.X)
        
        auto_btn = ttk.Button(
            btn_frame, 
            text="自动化", 
            command=self.show_automation_settings
        )
        auto_btn.pack(pady=10, padx=20, fill=tk.X)

    def show_author_info(self):
        """显示作者信息"""
        author_window = tk.Toplevel(self.root)
        author_window.title("关于作者")
        author_window.geometry("300x200")
        author_window.resizable(False, False)
        
        info_text = "QQ号: 2248850736\n\n邮箱: 2248850736@qq.com"
        info_label = tk.Label(
            author_window, 
            text=info_text, 
            font=("微软雅黑", 12),
            justify=tk.LEFT
        )
        info_label.pack(pady=40, padx=20)
        
        close_btn = ttk.Button(
            author_window, 
            text="关闭", 
            command=author_window.destroy
        )
        close_btn.pack(pady=10)

    # -------------------------- 自动化设置相关方法 --------------------------
    def show_automation_settings(self):
        """显示自动化设置窗口"""
        self.auto_window = tk.Toplevel(self.root)  # 标记窗口已打开
        self.auto_window.title("自动化设置")
        self.auto_window.geometry("450x400")
        self.auto_window.resizable(False, False)
        
        # 标题
        title_label = tk.Label(
            self.auto_window, 
            text="自动化任务配置", 
            font=("微软雅黑", 14, "bold"), 
            fg="#2c3e50"
        )
        title_label.pack(pady=15)
        
        # 时间选择区
        time_frame = ttk.LabelFrame(self.auto_window, text="执行时间（每天）")
        time_frame.pack(fill=tk.X, padx=30, pady=10)
        
        ttk.Label(time_frame, text="小时:").grid(row=0, column=0, padx=10, pady=10)
        self.hour_combo = ttk.Combobox(
            time_frame, 
            values=[f"{i:02d}" for i in range(24)],
            width=5, 
            state="readonly"
        )
        self.hour_combo.set("08")
        self.hour_combo.grid(row=0, column=1, padx=5, pady=10)
        
        ttk.Label(time_frame, text="分钟:").grid(row=0, column=2, padx=10, pady=10)
        self.minute_combo = ttk.Combobox(
            time_frame, 
            values=[f"{i:02d}" for i in range(60)],
            width=5, 
            state="readonly"
        )
        self.minute_combo.set("00")
        self.minute_combo.grid(row=0, column=3, padx=5, pady=10)
        
        # 执行模式选择区
        mode_frame = ttk.LabelFrame(self.auto_window, text="执行模式")
        mode_frame.pack(fill=tk.X, padx=30, pady=10)
        
        self.auto_mode_combo = ttk.Combobox(
            mode_frame, 
            values=["1. 全自动化（所有任务）", "2. 禁用APP任务（仅签到+小程序）", "3. 仅运行签到任务"],
            width=35, 
            state="readonly"
        )
        self.auto_mode_combo.current(0)
        self.auto_mode_combo.pack(padx=10, pady=10, fill=tk.X)
        
        # 启动/停止按钮
        self.auto_running = False
        self.auto_btn = ttk.Button(
            self.auto_window, 
            text="启动自动化", 
            command=self.toggle_automation
        )
        self.auto_btn.pack(pady=15)
        
        # 状态显示区
        self.status_label = ttk.Label(
            self.auto_window, 
            text="当前状态：未运行", 
            font=("微软雅黑", 10),
            fg="#e74c3c"
        )
        self.status_label.pack(pady=5)
        
        # 加载配置
        self.load_auto_config()
        
        # 窗口关闭事件
        self.auto_window.protocol("WM_DELETE_WINDOW", self.on_auto_window_close)

    def load_auto_config(self):
        """加载自动化配置"""
        if os.path.exists(AUTO_CONFIG_FILE):
            try:
                with open(AUTO_CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                self.hour_combo.set(config.get("hour", "08"))
                self.minute_combo.set(config.get("minute", "00"))
                
                mode_index = config.get("mode", 0)
                if 0 <= mode_index < 3:
                    self.auto_mode_combo.current(mode_index)
                
                self.auto_running = config.get("running", False)
                
                if self.auto_running and self.status_label:
                    self.auto_btn.config(text="停止自动化")
                    self.status_label.config(
                        text=f"当前状态：运行中（每天{self.hour_combo.get()}:{self.minute_combo.get()}执行）",
                        fg="#2ecc71"
                    )
                elif self.status_label:
                    self.auto_btn.config(text="启动自动化")
                    self.status_label.config(text="当前状态：未运行", fg="#e74c3c")
                
                logger.info("自动化配置加载成功")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"加载配置失败：{e}，使用默认配置")
        else:
            logger.info("未找到配置文件，使用默认配置")

    def save_auto_config(self):
        """保存自动化配置"""
        config = {
            "hour": self.hour_combo.get(),
            "minute": self.minute_combo.get(),
            "mode": self.auto_mode_combo.current(),
            "running": self.auto_running
        }
        
        try:
            with open(AUTO_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("配置保存成功")
        except Exception as e:
            logger.error(f"保存配置失败：{e}")

    def on_auto_window_close(self):
        """关闭自动化窗口时重置标记"""
        self.save_auto_config()
        self.auto_window.destroy()
        self.auto_window = None  # 重置为未打开

    def toggle_automation(self):
        """切换自动化状态（核心修复：通过auto_window判断窗口状态）"""
        if self.auto_window is None:
            messagebox.showwarning("提示", "请先打开自动化设置窗口！")
            return
            
        if not self.current_token:
            messagebox.showerror("错误", "请先选择或获取token！")
            return

        if not self.auto_running:
            # 启动自动化
            try:
                hour = int(self.hour_combo.get())
                minute = int(self.minute_combo.get())
                mode_index = self.auto_mode_combo.current()
                run_mode = [RunMode.FULL, RunMode.NO_APP_TASKS, RunMode.ONLY_CHECKIN][mode_index]

                # 移除旧任务
                if self.scheduler.get_job("auto_task"):
                    self.scheduler.remove_job("auto_task")

                # 添加定时任务
                self.scheduler.add_job(
                    func=self.auto_run_task,
                    args=[run_mode],
                    trigger="cron",
                    hour=hour,
                    minute=minute,
                    id="auto_task"
                )

                self.auto_running = True
                self.auto_btn.config(text="停止自动化")
                self.status_label.config(
                    text=f"当前状态：运行中（每天{hour:02d}:{minute:02d}执行）",
                    fg="#2ecc71"
                )
                logger.info(f"自动化启动成功，每天{hour:02d}:{minute:02d}执行（{self.get_mode_name(run_mode)}）")

            except Exception as e:
                logger.error(f"启动失败：{e}")
                messagebox.showerror("错误", f"启动失败：{str(e)}")
                return

        else:
            # 停止自动化
            try:
                if self.scheduler.get_job("auto_task"):
                    self.scheduler.remove_job("auto_task")

                self.auto_running = False
                self.auto_btn.config(text="启动自动化")
                self.status_label.config(text="当前状态：未运行", fg="#e74c3c")
                logger.info("自动化已停止")

            except Exception as e:
                logger.error(f"停止失败：{e}")
                messagebox.showerror("错误", f"停止失败：{str(e)}")
                return

        self.save_auto_config()

    def auto_run_task(self, run_mode):
        """自动化任务执行函数"""
        logger.info(f"\n===== 自动化任务启动（{self.get_mode_name(run_mode)}） =====")
        
        if not self.current_token:
            logger.error("无有效token，终止任务")
            return
        
        if self.task_thread and self.task_thread.is_alive():
            logger.warning("已有任务运行，跳过本次执行")
            return
        
        self.task_thread = threading.Thread(
            target=self._run_task_thread, args=(run_mode,), daemon=True
        )
        self.task_thread.start()

    def on_close(self):
        """程序关闭清理"""
        self.scheduler.shutdown()
        self.root.destroy()

# -------------------------- 程序入口 --------------------------
if __name__ == "__main__":
    # 确保必要文件存在
    for file in [TOKEN_FILE_PATH, PHONE_TOKEN_FILE, AUTO_CONFIG_FILE]:
        if not os.path.exists(file):
            with open(file, "w", encoding="utf-8") as f:
                if file.endswith(".json"):
                    json.dump({}, f)
                else:
                    f.write("")
    root = tk.Tk()
    app = PgAssistantGUI(root)
    root.mainloop()