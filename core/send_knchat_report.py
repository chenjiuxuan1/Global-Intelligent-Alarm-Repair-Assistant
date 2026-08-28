#!/usr/bin/env python3
"""
KN Chat (beforeve) Bot API 报告发送脚本

用于向 KN Chat 群聊机器人发送告警消息（Telegram Bot API 兼容格式）。

- API Base URL: https://bot.kn.chat
- 调用格式: /bot<TOKEN>/<METHOD>
- 配置项（环境变量，config/auto_load_env 支持）：
    KNCHAT_BOT_TOKEN  机器人 token（BotFather 创建机器人时获得）
    KNCHAT_CHAT_ID    目标群 chat_id（把机器人拉入群后，用 getUpdates 拿到）
    KNCHAT_BOT_API    可选，默认 https://bot.kn.chat
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_KNCHAT_BOT_API = "https://bot.kn.chat"


def send_knchat_message(
    message,
    chat_id=None,
    bot_token=None,
    api_base=None,
    parse_mode=None,
):
    """
    发送消息到 KN Chat 群聊机器人。

    Args:
        message: 消息文本
        chat_id: 目标群 chat_id（如 -1073805088）；默认读 KNCHAT_CHAT_ID
        bot_token: 机器人 token；默认读 KNCHAT_BOT_TOKEN
        api_base: Bot API Base URL；默认 https://bot.kn.chat
        parse_mode: 可选 'Markdown' / 'HTML'

    Returns:
        dict: {'success': True/False, 'status_code': int, 'response': str}
    """
    import os

    chat_id = chat_id or os.environ.get("KNCHAT_CHAT_ID", "").strip()
    bot_token = bot_token or os.environ.get("KNCHAT_BOT_TOKEN", "").strip()
    api_base = (api_base or os.environ.get("KNCHAT_BOT_API") or DEFAULT_KNCHAT_BOT_API).strip().rstrip("/")

    if not bot_token:
        return {
            "success": False,
            "status_code": None,
            "response": "缺少 KNCHAT_BOT_TOKEN",
        }
    if not chat_id:
        return {
            "success": False,
            "status_code": None,
            "response": "缺少 KNCHAT_CHAT_ID",
        }

    params = {
        "chat_id": chat_id,
        "text": message,
    }
    if parse_mode:
        params["parse_mode"] = parse_mode

    url = f"{api_base}/bot{bot_token}/sendMessage?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8", errors="replace")
            if 200 <= status_code < 300:
                return {
                    "success": True,
                    "status_code": status_code,
                    "response": response_body,
                }
            return {
                "success": False,
                "status_code": status_code,
                "response": response_body,
            }
    except urllib.error.HTTPError as exc:
        response_body = ""
        if exc.fp is not None:
            try:
                response_body = exc.fp.read().decode("utf-8", errors="replace")
            except Exception:
                response_body = ""
        return {
            "success": False,
            "status_code": exc.code,
            "response": response_body or str(exc.reason),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "status_code": None,
            "response": str(exc),
        }


def test_connection(bot_token=None, api_base=None):
    """
    用 getMe 验证 token 是否有效，并返回机器人信息。

    Returns:
        dict: {'success': bool, 'data': {...} or 'response': str}
    """
    import os

    bot_token = bot_token or os.environ.get("KNCHAT_BOT_TOKEN", "").strip()
    api_base = (api_base or os.environ.get("KNCHAT_BOT_API") or DEFAULT_KNCHAT_BOT_API).strip().rstrip("/")
    if not bot_token:
        return {"success": False, "response": "缺少 KNCHAT_BOT_TOKEN"}
    url = f"{api_base}/bot{bot_token}/getMe"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
            return {"success": body.get("ok"), "data": body.get("result")}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "response": str(exc)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KN Chat 机器人测试/发送")
    parser.add_argument("--test", action="store_true", help="用 getMe 验证 token")
    parser.add_argument("--message", default="📊 KN Chat 机器人连通性测试", help="要发送的消息")
    parser.add_argument("--chat-id", default=None)
    parser.add_argument("--bot-token", default=None)
    args = parser.parse_args()

    if args.test:
        result = test_connection(bot_token=args.bot_token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        result = send_knchat_message(
            args.message,
            chat_id=args.chat_id,
            bot_token=args.bot_token,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
