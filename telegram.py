"""Envío de mensajes a Telegram (Bot API). No registra nunca el token."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, token: str, chat_ids: list[str], dry_run: bool = False):
        self.token = token
        self.chat_ids = chat_ids
        self.dry_run = dry_run

    def send(self, text: str) -> bool:
        if self.dry_run or not self.token or not self.chat_ids:
            print(text, flush=True)
            return True
        ok = True
        for chat_id in self.chat_ids:
            ok = self._send_one(chat_id, text) and ok
        return ok

    def _send_one(self, chat_id: str, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for _ in range(3):
            try:
                r = requests.post(url, json=payload, timeout=15)
            except requests.RequestException as exc:
                # No se registra str(exc): la URL contiene el token.
                log.warning("Telegram: error de red (%s)", type(exc).__name__)
                time.sleep(1.5)
                continue
            if r.status_code == 429:
                try:
                    wait = float(r.json().get("parameters", {}).get("retry_after", 2))
                except (ValueError, AttributeError):
                    wait = 2.0
                time.sleep(min(wait, 30.0))
                continue
            if r.ok:
                return True
            log.error("Telegram: HTTP %s %s", r.status_code, r.text[:200])
            return False
        return False
