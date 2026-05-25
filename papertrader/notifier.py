from __future__ import annotations

import logging

import requests


class TelegramNotifier:
    def __init__(self, enabled: bool, bot_token: str, chat_id: str) -> None:
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message}
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover
            logging.warning("Telegram send failed: %s", exc)
