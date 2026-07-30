"""HTTP client for AgroDesk backend API. Bot never talks to PostgreSQL directly."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AccessError(str, Enum):
    UNREACHABLE = 'unreachable'
    BAD_SECRET = 'bad_secret'
    NOT_LINKED = 'not_linked'
    FORBIDDEN = 'forbidden'
    SERVER = 'server'
    UNKNOWN = 'unknown'


class ShiftOpKind(str, Enum):
    OK = 'ok'
    UNREACHABLE = 'unreachable'
    FORBIDDEN = 'forbidden'
    CONFLICT = 'conflict'
    VALIDATION = 'validation'
    SERVER = 'server'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class AccessResult:
    employee: dict[str, Any] | None
    error: AccessError | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.employee is not None and self.error is None


@dataclass(frozen=True)
class ShiftOpResult:
    """Result of open/close shift against AgroDesk API."""

    kind: ShiftOpKind
    data: dict[str, Any] | None = None
    status_code: int | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind == ShiftOpKind.OK and self.data is not None


USER_MESSAGES: dict[AccessError, str] = {
    AccessError.UNREACHABLE: (
        'Не удалось связаться с сервером АгроДеск.\n'
        'Проверьте интернет или повторите позже.'
    ),
    AccessError.BAD_SECRET: (
        'Ошибка конфигурации бота (секрет не совпадает с API).\n'
        'Обратитесь к администратору системы.'
    ),
    AccessError.NOT_LINKED: (
        'Вы не привязаны к системе АгроДеск.\n'
        'Сообщите менеджеру ваш Telegram ID: {tg_id}'
    ),
    AccessError.FORBIDDEN: (
        'Доступ запрещён. Обратитесь к администратору.'
    ),
    AccessError.SERVER: (
        'Сервер АгроДеск временно недоступен. Попробуйте позже.'
    ),
    AccessError.UNKNOWN: (
        'Не удалось авторизоваться. Попробуйте /start позже.'
    ),
}


def access_message(error: AccessError, tg_id: int) -> str:
    template = USER_MESSAGES.get(error, USER_MESSAGES[AccessError.UNKNOWN])
    return template.format(tg_id=tg_id)


def parse_api_detail(response: httpx.Response | None) -> str | None:
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        text = (response.text or '').strip()
        return text[:300] or None
    if isinstance(payload, dict):
        detail = payload.get('detail')
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list):
            parts: list[str] = []
            for item in detail:
                if isinstance(item, dict):
                    msg = item.get('msg') or item.get('message')
                    loc = item.get('loc')
                    if msg and loc:
                        parts.append(f"{'.'.join(str(x) for x in loc)}: {msg}")
                    elif msg:
                        parts.append(str(msg))
                else:
                    parts.append(str(item))
            if parts:
                return '; '.join(parts)[:300]
    text = (response.text or '').strip()
    return text[:300] or None


def classify_shift_response(response: httpx.Response | None) -> ShiftOpResult:
    if response is None:
        return ShiftOpResult(kind=ShiftOpKind.UNREACHABLE, detail='Нет ответа от API')
    detail = parse_api_detail(response)
    code = response.status_code
    if code in (200, 201):
        try:
            data = response.json()
        except Exception:
            return ShiftOpResult(
                kind=ShiftOpKind.UNKNOWN,
                status_code=code,
                detail='Некорректный ответ API',
            )
        if not isinstance(data, dict):
            return ShiftOpResult(
                kind=ShiftOpKind.UNKNOWN,
                status_code=code,
                detail='Некорректный ответ API',
            )
        return ShiftOpResult(kind=ShiftOpKind.OK, data=data, status_code=code)
    if code in (401, 403):
        return ShiftOpResult(
            kind=ShiftOpKind.FORBIDDEN,
            status_code=code,
            detail=detail or 'Недостаточно прав',
        )
    if code == 409:
        return ShiftOpResult(
            kind=ShiftOpKind.CONFLICT,
            status_code=code,
            detail=detail or 'Конфликт данных',
        )
    if code in (400, 422):
        return ShiftOpResult(
            kind=ShiftOpKind.VALIDATION,
            status_code=code,
            detail=detail or 'Ошибка данных запроса',
        )
    if code >= 500:
        return ShiftOpResult(
            kind=ShiftOpKind.SERVER,
            status_code=code,
            detail=detail or f'HTTP {code}',
        )
    return ShiftOpResult(
        kind=ShiftOpKind.UNKNOWN,
        status_code=code,
        detail=detail or f'HTTP {code}',
    )


def shift_op_user_message(result: ShiftOpResult, *, action: str = 'открыть') -> str:
    """User-facing text: network/5xx vs business/validation errors."""
    if result.kind == ShiftOpKind.UNREACHABLE:
        return (
            f'❌ Нет связи с API АгроДеск — не удалось {action} смену.\n'
            'Проверьте интернет или сообщите администратору (API_BASE_URL).'
        )
    if result.kind == ShiftOpKind.SERVER:
        return (
            f'❌ Сервер АгроДеск временно недоступен — не удалось {action} смену.\n'
            'Повторите позже.'
        )
    if result.kind == ShiftOpKind.FORBIDDEN:
        return (
            f'❌ Нет прав, чтобы {action} смену.\n'
            f'{result.detail or "Обратитесь к администратору."}'
        )
    if result.kind == ShiftOpKind.CONFLICT:
        return f'❌ {result.detail or "Уже есть открытая смена."}'
    if result.kind == ShiftOpKind.VALIDATION:
        return (
            f'❌ Ошибка данных — не удалось {action} смену.\n'
            f'{result.detail or "Проверьте объект, тип работ и поле."}'
        )
    return (
        f'❌ Не удалось {action} смену.\n'
        f'{result.detail or "Связь с API есть, но запрос отклонён. "
          "Повторите позже или откройте смену в веб-приложении."}'
    )


class ApiClient:
    BASE = settings.api_base_url.rstrip('/')
    _tokens: dict[int, str] = {}

    def __init__(self) -> None:
        self.timeout = settings.request_timeout
        self.retries = settings.request_retries

    async def health_check(self) -> tuple[bool, str]:
        """GET /api/health — no auth. Returns (ok, detail)."""
        url = f'{self.BASE}/api/health'
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
            if response.status_code == 200:
                return True, f'OK {response.status_code}'
            return False, f'HTTP {response.status_code}: {response.text[:200]}'
        except Exception as exc:
            return False, f'{type(exc).__name__}: {exc}'

    async def resolve_access(self, tg_id: int) -> AccessResult:
        """Auth + /employees/me with classified errors for user-facing messages."""
        token, auth_error = await self._get_token_result(tg_id)
        if auth_error is not None:
            return AccessResult(employee=None, error=auth_error)
        if not token:
            return AccessResult(employee=None, error=AccessError.UNKNOWN)

        response = await self._request(tg_id, 'GET', '/api/employees/me')
        if response is None:
            return AccessResult(employee=None, error=AccessError.UNREACHABLE)
        if response.status_code == 401:
            self.invalidate_token(tg_id)
            return AccessResult(employee=None, error=AccessError.NOT_LINKED)
        if response.status_code == 403:
            return AccessResult(employee=None, error=AccessError.FORBIDDEN)
        if response.status_code >= 500:
            return AccessResult(employee=None, error=AccessError.SERVER, detail=response.text[:200])
        if response.status_code != 200:
            return AccessResult(
                employee=None,
                error=AccessError.UNKNOWN,
                detail=f'{response.status_code}: {response.text[:200]}',
            )
        try:
            data = response.json()
        except Exception:
            logger.exception('get_employee parse failed')
            return AccessResult(employee=None, error=AccessError.UNKNOWN)
        if not isinstance(data, dict):
            return AccessResult(employee=None, error=AccessError.UNKNOWN)
        return AccessResult(employee=data)

    async def _get_token_result(self, tg_id: int) -> tuple[str | None, AccessError | None]:
        cached = self._tokens.get(tg_id)
        if cached:
            return cached, None

        last_error: AccessError | None = AccessError.UNREACHABLE
        for attempt in range(self.retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f'{self.BASE}/api/auth/bot-token',
                        json={
                            'telegram_id': tg_id,
                            'secret': settings.bot_internal_secret,
                        },
                    )
                if response.status_code == 200:
                    token = response.json().get('access_token')
                    if not token:
                        return None, AccessError.UNKNOWN
                    self._tokens[tg_id] = str(token)
                    return self._tokens[tg_id], None
                if response.status_code == 403:
                    logger.error(
                        'bot-token forbidden for tg_id=%s — check BOT_INTERNAL_SECRET',
                        tg_id,
                    )
                    return None, AccessError.BAD_SECRET
                if response.status_code == 404:
                    return None, AccessError.NOT_LINKED
                if response.status_code == 429:
                    last_error = AccessError.SERVER
                    logger.warning('bot-token rate limited tg_id=%s', tg_id)
                    return None, last_error
                if response.status_code >= 500:
                    last_error = AccessError.SERVER
                    logger.warning(
                        'bot-token server error tg_id=%s status=%s body=%s',
                        tg_id,
                        response.status_code,
                        response.text[:300],
                    )
                else:
                    last_error = AccessError.UNKNOWN
                    logger.warning(
                        'bot-token failed tg_id=%s status=%s body=%s',
                        tg_id,
                        response.status_code,
                        response.text[:300],
                    )
                    return None, last_error
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                last_error = AccessError.UNREACHABLE
                logger.warning(
                    'bot-token network error tg_id=%s attempt=%s: %s',
                    tg_id,
                    attempt + 1,
                    exc,
                )
            except Exception:
                last_error = AccessError.UNKNOWN
                logger.exception('bot-token unexpected error tg_id=%s', tg_id)
                return None, last_error

            if attempt < self.retries:
                await asyncio.sleep(0.4 * (attempt + 1))

        return None, last_error

    async def _get_token(self, tg_id: int) -> str | None:
        token, _error = await self._get_token_result(tg_id)
        return token

    @staticmethod
    def _h(token: str) -> dict[str, str]:
        return {'Authorization': f'Bearer {token}'}

    async def _request(
        self,
        tg_id: int,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> httpx.Response | None:
        token = await self._get_token(tg_id)
        if not token:
            return None

        url = f'{self.BASE}{path}'
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=self._h(token),
                        json=json,
                        params=params,
                    )
                if response.status_code == 401 and retry_auth:
                    self.invalidate_token(tg_id)
                    return await self._request(
                        tg_id,
                        method,
                        path,
                        json=json,
                        params=params,
                        retry_auth=False,
                    )
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                last_exc = exc
                logger.warning(
                    '%s %s network error tg_id=%s attempt=%s: %s',
                    method,
                    path,
                    tg_id,
                    attempt + 1,
                    exc,
                )
                if attempt < self.retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
            except Exception:
                logger.exception('%s %s failed for tg_id=%s', method, path, tg_id)
                return None

        if last_exc is not None:
            logger.error('%s %s gave up for tg_id=%s: %s', method, path, tg_id, last_exc)
        return None

    async def get_employee(self, tg_id: int) -> dict | None:
        result = await self.resolve_access(tg_id)
        return result.employee

    async def is_admin(self, tg_id: int) -> bool:
        employee = await self.get_employee(tg_id)
        if not employee:
            return False
        return str(employee.get('role', '')) in ('admin', 'manager')

    async def get_locations(self, tg_id: int) -> list[dict]:
        return await self._get_list(tg_id, '/api/locations', params={'is_active': True})

    async def get_work_types(self, tg_id: int) -> list[dict]:
        return await self._get_list(tg_id, '/api/work-types', params={'is_active': True})

    async def get_equipment(self, tg_id: int) -> list[dict]:
        return await self._get_list(tg_id, '/api/equipment', params={'is_active': True})

    async def get_fields(self, tg_id: int) -> list[dict]:
        return await self._get_list(tg_id, '/api/fields')

    async def get_agro_plans_today(self, tg_id: int) -> list[dict]:
        return await self._get_list(tg_id, '/api/agro-plan/today')

    async def open_shift(
        self,
        tg_id: int,
        location_id: str,
        work_type_id: str,
        equipment_id: str | None,
        lat: float | None,
        lng: float | None,
        field_id: str | None = None,
        agro_plan_id: str | None = None,
        implement_id: str | None = None,
    ) -> ShiftOpResult:
        body: dict[str, Any] = {
            'location_id': location_id,
            'work_type_id': work_type_id,
            'latitude': lat,
            'longitude': lng,
        }
        if equipment_id:
            body['equipment_id'] = equipment_id
        if field_id:
            body['field_id'] = field_id
        if agro_plan_id:
            body['agro_plan_id'] = agro_plan_id
        if implement_id:
            body['implement_id'] = implement_id
        response = await self._request(tg_id, 'POST', '/api/shifts', json=body)
        result = classify_shift_response(response)
        if not result.ok:
            logger.warning(
                'open_shift tg_id=%s kind=%s status=%s detail=%s',
                tg_id,
                result.kind.value,
                result.status_code,
                result.detail,
            )
        return result

    async def close_shift(self, tg_id: int, description: str) -> ShiftOpResult:
        active = await self.get_active_shift(tg_id)
        if not active:
            return ShiftOpResult(
                kind=ShiftOpKind.CONFLICT,
                detail='Нет открытой смены для закрытия',
            )
        shift_id = active.get('id')
        if not shift_id:
            return ShiftOpResult(
                kind=ShiftOpKind.UNKNOWN,
                detail='Открытая смена без id',
            )
        return await self.close_shift_for_employee(tg_id, str(shift_id), description)

    async def get_active_shift(self, tg_id: int) -> dict | None:
        """Own open shift only (managers/admins must not pick a colleague's row)."""
        employee = await self.get_employee(tg_id)
        if not employee:
            return None
        emp_id = employee.get('id')
        params: dict[str, Any] = {'status': 'open'}
        if emp_id:
            params['employee_id'] = str(emp_id)
        shifts = await self._get_list(tg_id, '/api/shifts', params=params)
        if not shifts:
            return None
        # Prefer exact match if API returned mixed rows
        if emp_id:
            for shift in shifts:
                if str(shift.get('employee_id') or '') == str(emp_id):
                    return shift
        return shifts[0]

    async def get_all_employees(self, tg_id: int) -> list[dict]:
        return await self._get_list(tg_id, '/api/employees', params={'is_active': True})

    async def get_shifts_for_date(self, tg_id: int, date_str: str) -> list[dict]:
        return await self._get_list(
            tg_id,
            '/api/shifts',
            params={'from_date': date_str, 'to_date': date_str},
        )

    async def open_shift_for_employee(
        self,
        admin_tg_id: int,
        employee_id: str,
        location_id: str,
        work_type_id: str,
        equipment_id: str | None,
        start_time: str,
        end_time: str,
        description: str,
        field_id: str | None = None,
    ) -> ShiftOpResult:
        shift_date, start_t = self._split_datetime(start_time)
        _, end_t = self._split_datetime(end_time)
        if shift_date is None or start_t is None or end_t is None:
            logger.warning('open_shift_for_employee: invalid datetime %s / %s', start_time, end_time)
            return ShiftOpResult(
                kind=ShiftOpKind.VALIDATION,
                detail='Некорректная дата/время смены',
            )

        body: dict[str, Any] = {
            'employee_id': employee_id,
            'date': shift_date,
            'start_time': start_t,
            'end_time': end_t,
            'location_id': location_id,
            'work_type_id': work_type_id,
            'description': description or None,
        }
        if equipment_id:
            body['equipment_id'] = equipment_id
        if field_id:
            body['field_id'] = field_id
        response = await self._request(admin_tg_id, 'POST', '/api/shifts/manual', json=body)
        result = classify_shift_response(response)
        if not result.ok:
            logger.warning(
                'open_shift_for_employee kind=%s status=%s detail=%s',
                result.kind.value,
                result.status_code,
                result.detail,
            )
        return result

    async def close_shift_for_employee(
        self,
        admin_tg_id: int,
        shift_id: str,
        description: str,
    ) -> ShiftOpResult:
        response = await self._request(
            admin_tg_id,
            'POST',
            f'/api/shifts/{shift_id}/close',
            json={'description': description},
        )
        result = classify_shift_response(response)
        if not result.ok:
            logger.warning(
                'close_shift kind=%s status=%s detail=%s',
                result.kind.value,
                result.status_code,
                result.detail,
            )
        return result

    async def get_active_shifts_all(self, admin_tg_id: int) -> list[dict]:
        return await self._get_list(admin_tg_id, '/api/shifts', params={'status': 'open'})

    async def get_dashboard_stats(self, tg_id: int) -> dict | None:
        response = await self._request(tg_id, 'GET', '/api/dashboard/stats')
        if response is None or response.status_code != 200:
            if response is not None:
                logger.warning('get_dashboard_stats status=%s', response.status_code)
            return None
        try:
            return response.json()
        except Exception:
            logger.exception('get_dashboard_stats parse failed')
            return None

    async def get_org_settings(self, tg_id: int) -> dict | None:
        response = await self._request(tg_id, 'GET', '/api/settings/organization')
        if response is None or response.status_code != 200:
            return None
        try:
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            logger.exception('get_org_settings parse failed')
            return None

    def invalidate_token(self, tg_id: int) -> None:
        self._tokens.pop(tg_id, None)

    async def _get_list(
        self,
        tg_id: int,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict]:
        response = await self._request(tg_id, 'GET', path, params=params)
        if response is None or response.status_code != 200:
            if response is not None:
                logger.warning('%s status=%s', path, response.status_code)
            return []
        try:
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception('parse list failed for %s', path)
            return []

    @staticmethod
    def _split_datetime(value: str) -> tuple[str | None, str | None]:
        raw = str(value or '').strip()
        if not raw:
            return None, None

        normalized = raw.replace('T', ' ')
        if ' ' in normalized:
            date_part, time_part = normalized.split(' ', 1)
            time_part = time_part[:8]
            if len(time_part) == 5:
                time_part = f'{time_part}:00'
            try:
                date.fromisoformat(date_part)
                time.fromisoformat(time_part)
            except ValueError:
                return None, None
            return date_part, time_part

        if len(raw) == 10:
            try:
                date.fromisoformat(raw)
            except ValueError:
                return None, None
            return raw, '00:00:00'

        try:
            parsed = datetime.fromisoformat(raw)
            return parsed.date().isoformat(), parsed.time().replace(microsecond=0).isoformat()
        except ValueError:
            try:
                time.fromisoformat(raw if len(raw) > 5 else f'{raw}:00')
            except ValueError:
                return None, None
            return date.today().isoformat(), raw if len(raw) > 5 else f'{raw}:00'
