#!/usr/bin/env python3
"""Pre/post deploy self-check for AgroDesk Telegram bot.

Run from bot/ directory:
  python scripts/self_check.py
  python scripts/self_check.py --telegram-id 111111111
  python scripts/self_check.py --with-shifts   # dev only: open+close test shift

Exit code 0 = all checks passed, 1 = at least one failure.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

BOT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_ROOT))

from dotenv import load_dotenv

load_dotenv(BOT_ROOT / '.env')

from app.config import settings  # noqa: E402
from app.services.api_client import ApiClient  # noqa: E402

_DEFAULT_SECRET = 'agrodesk-bot-secret-change-me'


class CheckResult:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(f'  [OK]   {msg}')

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f'  [FAIL] {msg}')

    @property
    def success(self) -> bool:
        return len(self.failed) == 0


def check_env(results: CheckResult) -> None:
    print('\n== Env ==')
    for name in ('BOT_TOKEN', 'API_BASE_URL', 'BOT_INTERNAL_SECRET'):
        if (os.environ.get(name) or '').strip():
            results.ok(f'{name} is set')
        else:
            results.fail(f'{name} is missing')

    if settings.bot_internal_secret == _DEFAULT_SECRET:
        results.fail('BOT_INTERNAL_SECRET is default placeholder — change before production')
    else:
        results.ok('BOT_INTERNAL_SECRET is not the default placeholder')

    if any(h in settings.api_base_url.lower() for h in ('localhost', '127.0.0.1')):
        results.fail(f'API_BASE_URL looks local: {settings.api_base_url}')
    else:
        results.ok(f'API_BASE_URL is public: {settings.api_base_url}')

    if settings.api_base_url.startswith('https://'):
        results.ok('API_BASE_URL uses HTTPS')
    elif settings.api_base_url.startswith('http://'):
        print('  [WARN] API_BASE_URL uses HTTP — HTTPS recommended for production')
        results.ok('API_BASE_URL reachable scheme (HTTP)')


async def check_telegram_token(results: CheckResult) -> None:
    print('\n== Telegram ==')
    url = f'https://api.telegram.org/bot{settings.bot_token}/getMe'
    try:
        async with httpx.AsyncClient(timeout=settings.telegram_timeout) as client:
            response = await client.get(url)
        if response.status_code == 200 and response.json().get('ok'):
            username = response.json().get('result', {}).get('username', '?')
            results.ok(f'BOT_TOKEN valid (@{username})')
        else:
            results.fail(f'BOT_TOKEN invalid: HTTP {response.status_code} {response.text[:120]}')
    except Exception as exc:
        results.fail(f'Cannot reach Telegram API: {exc}')


async def check_api_health(results: CheckResult) -> None:
    print('\n== AgroDesk API ==')
    api = ApiClient()
    ok, detail = await api.health_check()
    if ok:
        results.ok(f'GET /api/health — {detail}')
    else:
        results.fail(f'GET /api/health — {detail}')
        results.fail('Check API_BASE_URL, firewall, nginx, and that API is running')


async def check_bot_token_auth(results: CheckResult, telegram_id: int | None) -> str | None:
    print('\n== Bot auth ==')
    if telegram_id is None:
        results.fail('No --telegram-id: skip bot-token test (pass demo ID, e.g. 111111111)')
        return None

    url = f'{settings.api_base_url.rstrip("/")}/api/auth/bot-token'
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            bad = await client.post(
                url,
                json={'telegram_id': telegram_id, 'secret': 'wrong-secret'},
            )
            if bad.status_code == 403:
                results.ok('bot-token rejects wrong secret (403)')
            else:
                results.fail(f'bot-token wrong secret expected 403, got {bad.status_code}')

            response = await client.post(
                url,
                json={'telegram_id': telegram_id, 'secret': settings.bot_internal_secret},
            )
    except Exception as exc:
        results.fail(f'bot-token request failed: {exc}')
        return None

    if response.status_code == 404:
        results.fail(
            f'Telegram ID {telegram_id} not linked to employee (404). '
            'Link in web panel: PATCH /api/employees/{{id}}/link-telegram'
        )
        return None
    if response.status_code == 403:
        results.fail('BOT_INTERNAL_SECRET mismatch with API (403)')
        return None
    if response.status_code != 200:
        results.fail(f'bot-token failed: HTTP {response.status_code} {response.text[:200]}')
        return None

    token = response.json().get('access_token')
    if not token:
        results.fail('bot-token response missing access_token')
        return None

    results.ok(f'bot-token OK for telegram_id={telegram_id}')
    return str(token)


async def check_employee_me(results: CheckResult, telegram_id: int | None) -> None:
    if telegram_id is None:
        return
    print('\n== Employee ==')
    api = ApiClient()
    access = await api.resolve_access(telegram_id)
    if access.ok and access.employee:
        name = access.employee.get('full_name') or access.employee.get('employee_code')
        role = access.employee.get('role', '?')
        results.ok(f'GET /api/employees/me — {name} (role={role})')
    else:
        results.fail(f'GET /api/employees/me — error={access.error} detail={access.detail}')


async def check_shift_cycle(results: CheckResult, telegram_id: int | None) -> None:
    if telegram_id is None:
        return
    print('\n== Shift cycle (dev) ==')
    api = ApiClient()
    active = await api.get_active_shift(telegram_id)
    if active:
        results.ok(f'Active shift already open id={active.get("id")} — skip open test')
        return

    locations = await api.get_locations(telegram_id)
    work_types = await api.get_work_types(telegram_id)
    if not locations or not work_types:
        results.fail('Cannot test shift: empty locations or work_types')
        return

    loc_id = str(locations[0]['id'])
    wt_id = str(work_types[0]['id'])
    opened = await api.open_shift(telegram_id, loc_id, wt_id, None, None, None)
    if not opened:
        results.fail('POST /api/shifts — open failed')
        return
    results.ok(f'POST /api/shifts — opened id={opened.get("id")}')

    closed = await api.close_shift(telegram_id, 'Smoke test shift close')
    if not closed:
        results.fail('POST /api/shifts/close — close failed')
        return
    results.ok('POST /api/shifts/close — closed')


def _parse_telegram_id(raw: str | None) -> int | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


async def run(args: argparse.Namespace) -> int:
    print('AgroDesk bot self-check')
    print(f'  API_BASE_URL={settings.api_base_url}')
    print(f'  AGRODESK_ENV={settings.agrodesk_env}')

    results = CheckResult()
    check_env(results)
    await check_telegram_token(results)
    await check_api_health(results)
    await check_bot_token_auth(results, args.telegram_id)
    await check_employee_me(results, args.telegram_id)

    if args.with_shifts:
        if settings.is_production:
            results.fail('--with-shifts is disabled when AGRODESK_ENV=production')
        else:
            await check_shift_cycle(results, args.telegram_id)

    print('\n== Summary ==')
    print(f'  Passed: {len(results.passed)}')
    print(f'  Failed: {len(results.failed)}')

    if results.failed:
        print('\nDiagnostics:')
        for hint in _diagnostic_hints(results.failed):
            print(f'  • {hint}')
        return 1

    print('\nAll checks passed.')
    return 0


def _diagnostic_hints(failures: list[str]) -> list[str]:
    hints: list[str] = []
    joined = ' '.join(failures).lower()
    if 'health' in joined or 'unreachable' in joined or 'api_base_url' in joined:
        hints.append('API unreachable — verify URL, nginx /api proxy, port 3010/443 open on VPS')
    if '403' in joined or 'secret' in joined:
        hints.append('BOT_INTERNAL_SECRET must match exactly on bothost and backend .env')
    if '404' in joined or 'not linked' in joined:
        hints.append('Link Telegram ID in web: Employees → Telegram ID → Привязать')
    if 'bot_token' in joined or 'telegram' in joined:
        hints.append('Check BOT_TOKEN from @BotFather in bothost env')
    if not hints:
        hints.append('See docs/bot-bothost.md')
    return hints


def main() -> None:
    parser = argparse.ArgumentParser(description='AgroDesk bot deploy self-check')
    parser.add_argument(
        '--telegram-id',
        type=int,
        default=None,
        help='Linked employee Telegram ID (or set SMOKE_TELEGRAM_ID)',
    )
    parser.add_argument(
        '--with-shifts',
        action='store_true',
        help='Open and close a test shift (dev only, not production)',
    )
    args = parser.parse_args()
    telegram_id = args.telegram_id or _parse_telegram_id(os.environ.get('SMOKE_TELEGRAM_ID'))
    args.telegram_id = telegram_id
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
