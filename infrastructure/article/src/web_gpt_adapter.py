"""Project boundary for the source-referenced web_gpt tool."""

import importlib
import json
import os
import sys
import tempfile
import urllib.request
from contextlib import contextmanager
from core.api import paths__WorkspacePath as Path
from urllib.parse import urlsplit


def import_root() -> Path:
    return Path(os.environ.get("WEB_GPT_IMPORT_ROOT", os.environ.get("WEB_GPT_PARENT", "/Users/xiaoyanhao/project/chatgpt_playwright"))).expanduser().resolve()


def check_browser(provider="chatgpt") -> dict:
    if provider not in {"chatgpt", "qwen", "deepseek"}:
        raise ValueError("provider 必须是 chatgpt、qwen 或 deepseek")
    if sys.platform != "darwin":
        raise RuntimeError("web_gpt 当前只支持 macOS；Windows 仍可使用文献筛选功能。")
    if not (import_root() / "web_gpt/__init__.py").is_file():
        raise RuntimeError("找不到 web_gpt，请检查 WEB_GPT_IMPORT_ROOT。")
    url = os.environ.get({"qwen":"WEB_QWEN_CDP_URL","deepseek":"WEB_DEEPSEEK_CDP_URL"}.get(provider,"WEB_GPT_CDP_URL"), os.environ.get("WEB_GPT_CDP_URL", "http://127.0.0.1:9222"))
    url = url.rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("WEB_GPT_CDP_URL 必须指向本机专用 Chrome。")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/json/version", timeout=3) as response:
            version = json.load(response)
        if not version.get("webSocketDebuggerUrl"):
            raise ValueError("not a Chrome debugging endpoint")
    except Exception as exc:
        raise RuntimeError("专用 GPT 浏览器未连接。请先运行 open_gpt.command，在打开的 Chrome 中登录 ChatGPT，再点击生成。") from exc
    return {"connected": True, "browser": version.get("Browser", "Chrome"), "login_verified": False}


@contextmanager
def gpt_session(provider="chatgpt", *, qwen_site="international", model=None, thinking_high=None):
    check_browser(provider)
    import fcntl

    # All Literature Explorer processes coordinate; unrelated consumers still
    # need to avoid using this browser/clipboard at the same time.
    lock_path = Path(tempfile.gettempdir()) / f"literature-explorer-web-gpt-{os.getuid()}.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("本项目已有 GPT 调用正在运行，请等待完成。") from exc
        try:
            parent = str(import_root())
            if parent not in sys.path:
                sys.path.insert(0, parent)
            # web_gpt's urllib/CDP probes must bypass system HTTP proxies.
            for name in ("NO_PROXY", "no_proxy"):
                values = [v for v in os.environ.get(name, "").split(",") if v]
                os.environ[name] = ",".join(dict.fromkeys(values + ["localhost", "127.0.0.1", "::1"]))
            module = importlib.import_module("web_gpt")
            if provider == "chatgpt":
                if model is not None or qwen_site != "international":
                    raise ValueError("Qwen选项不能传给GPT")
                session = module.ChatGPTWeb(new_chat=True, thinking_high=False if thinking_high is None else thinking_high)
            else:
                session = module.create_session(provider, new_chat=True, site=qwen_site,
                    model=model, thinking_high=True if thinking_high is None else thinking_high)
            with session as gpt:
                yield gpt
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
