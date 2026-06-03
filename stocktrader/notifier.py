"""
Telegram notifier.
"""
from __future__ import annotations

import logging
import urllib.request
import urllib.parse


class Notifier:
    def __init__(self, enabled: bool, token: str, chat_id: str) -> None:
        self.enabled  = enabled
        self.token    = token
        self.chat_id  = chat_id

    def send(self, message: str) -> None:
        logging.info("[NOTIFY] %s", message)
        if not self.enabled or not self.token or not self.chat_id:
            return
        try:
            url    = f"https://api.telegram.org/bot{self.token}/sendMessage"
            params = urllib.parse.urlencode({"chat_id": self.chat_id, "text": message})
            urllib.request.urlopen(f"{url}?{params}", timeout=5)
        except Exception as exc:
            logging.warning("Telegram mislukt: %s", exc)
