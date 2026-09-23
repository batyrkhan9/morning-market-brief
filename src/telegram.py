"""Telegram Bot API: send message, send photo. The only file that talks to api.telegram.org from Python."""
import os

import requests

from src.retry import retry

MAX_MESSAGE = 4096
MAX_CAPTION = 1024


def token():
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    return tok


def _call(method, payload=None, files=None):
    resp = requests.post(f"https://api.telegram.org/bot{token()}/{method}", data=payload, files=files, timeout=60)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description', resp.text[:200])}")
    return data["result"]


def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    if len(text) > MAX_MESSAGE:
        raise ValueError(f"message is {len(text)} characters, Telegram allows {MAX_MESSAGE}")
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)
    return retry(_call, "sendMessage", payload)


def send_photo(chat_id, path, caption=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "parse_mode": parse_mode}
    if caption:
        payload["caption"] = caption[:MAX_CAPTION]
    with open(path, "rb") as f:
        return retry(_call, "sendPhoto", payload, {"photo": f})


def set_webhook(url, secret):
    return retry(_call, "setWebhook", {"url": url, "secret_token": secret, "allowed_updates": '["message"]'})


def get_webhook_info():
    return retry(_call, "getWebhookInfo")
