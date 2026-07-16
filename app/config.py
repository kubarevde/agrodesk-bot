"""Bot settings — only env vars; no backend/DB imports."""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_SECRET = 'agrodesk-bot-secret-change-me'
_LOCAL_URL_HINTS = ('localhost', '127.0.0.1', '0.0.0.0', '::1')

# Bothost panel / legacy names → canonical env keys
_ENV_ALIASES: dict[str, str] = {
    'BOTTOKEN': 'BOT_TOKEN',
    'APIBASEURL': 'API_BASE_URL',
    'BOTINTERNALSECRET': 'BOT_INTERNAL_SECRET',
    'LOGLEVEL': 'LOG_LEVEL',
}


def _normalize_env_aliases() -> None:
    for alias, canonical in _ENV_ALIASES.items():
        alias_val = (os.environ.get(alias) or '').strip()
        canonical_val = (os.environ.get(canonical) or '').strip()
        if alias_val and not canonical_val:
            os.environ[canonical] = alias_val


_normalize_env_aliases()


def _require(name: str) -> str:
    value = (os.environ.get(name) or '').strip()
    if not value:
        raise RuntimeError(
            f'Missing required env var {name}. '
            f'See bot/.env.example, bot/bot.env.example and docs/bot-bothost.md'
        )
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f'{name} must be an integer, got {raw!r}') from exc


def _float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or '').strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f'{name} must be a number, got {raw!r}') from exc


class Settings:
    bot_token: str
    api_base_url: str
    bot_internal_secret: str
    agrodesk_env: str
    log_level: str
    request_timeout: float
    request_retries: int
    telegram_timeout: float
    polling_timeout: int
    run_mode: str  # polling | webhook (webhook not implemented — use polling on bothost)
    sheets_mirror_enabled: bool
    google_sheets_name: str
    google_creds_path: str
    google_creds_json: str | None

    def __init__(self) -> None:
        self.agrodesk_env = (os.environ.get('AGRODESK_ENV') or 'development').strip().lower()
        self.bot_token = _require('BOT_TOKEN')
        self.api_base_url = _require('API_BASE_URL').rstrip('/')
        self.bot_internal_secret = _require('BOT_INTERNAL_SECRET')
        self.log_level = (os.environ.get('LOG_LEVEL') or 'INFO').upper()
        self.request_timeout = _float('REQUEST_TIMEOUT', 15.0)
        self.request_retries = max(0, _int('REQUEST_RETRIES', 2))
        self.telegram_timeout = _float('TELEGRAM_TIMEOUT', 60.0)
        self.polling_timeout = max(10, _int('POLLING_TIMEOUT', 30))
        self.run_mode = (os.environ.get('BOT_RUN_MODE') or 'polling').strip().lower()

        self.sheets_mirror_enabled = _bool('SHEETS_MIRROR_ENABLED', False)
        self.google_sheets_name = os.environ.get('GOOGLE_SHEETS_NAME', 'worktime_bot')
        self.google_creds_path = os.environ.get(
            'GOOGLE_CREDS_PATH',
            'credentials/service_account.json',
        )
        self.google_creds_json = os.environ.get('GOOGLE_CREDS_JSON') or None

        self._validate()

    @property
    def is_production(self) -> bool:
        return self.agrodesk_env in ('production', 'prod')

    def _validate(self) -> None:
        if self.is_production and self.bot_internal_secret == _DEFAULT_SECRET:
            raise RuntimeError(
                'BOT_INTERNAL_SECRET is the default placeholder. '
                'Set a strong unique secret in bothost env AND on AgroDesk API (AGRODESK_ENV=production).'
            )
        if self.bot_internal_secret == _DEFAULT_SECRET:
            logger.warning(
                'BOT_INTERNAL_SECRET is the default placeholder — '
                'set a strong unique secret on bothost AND on AgroDesk API'
            )
        if any(h in self.api_base_url.lower() for h in _LOCAL_URL_HINTS):
            if self.is_production:
                raise RuntimeError(
                    f'API_BASE_URL looks local ({self.api_base_url}). '
                    'On bothost.ru set the public URL of AgroDesk, e.g. https://your-domain.ru'
                )
            logger.warning(
                'API_BASE_URL looks local (%s). On bothost.ru use the public HTTPS URL '
                'of AgroDesk, e.g. https://your-domain.ru',
                self.api_base_url,
            )
        if self.api_base_url.startswith('http://') and not any(
            h in self.api_base_url.lower() for h in _LOCAL_URL_HINTS
        ):
            logger.warning(
                'API_BASE_URL uses HTTP without TLS (%s). Prefer HTTPS in production.',
                self.api_base_url,
            )
        if self.run_mode not in ('polling', 'webhook'):
            raise RuntimeError(f'BOT_RUN_MODE must be polling or webhook, got {self.run_mode!r}')
        if self.run_mode == 'webhook':
            logger.warning(
                'BOT_RUN_MODE=webhook is not implemented; bothost.ru deployment uses polling'
            )


try:
    settings = Settings()
except RuntimeError as exc:
    print(f'[agrodesk-bot] config error: {exc}', file=sys.stderr)
    raise
