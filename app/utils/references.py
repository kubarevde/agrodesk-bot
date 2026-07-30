"""Helpers for locations / work types / fields from AgroDesk API payloads."""

from __future__ import annotations

from typing import Any

# Aligned with backend migration 022_agro_calendar_shift_link backfill
_FIELD_WORK_NAMES = frozenset(
    {
        'Посев',
        'Уборка урожая',
        'Культивация',
        'Боронование',
        'Опрыскивание',
        'Полив',
        'Пахота',
    }
)


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    needle = (name or '').strip()
    for item in items:
        if str(item.get('name', '')).strip() == needle:
            return item
    return None


def _coerce_bool(value: Any) -> bool | None:
    """Return True/False for known flag shapes, None if absent/unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'да', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'нет', 'off', ''}:
            return False
    return None


def is_field_work_type(item: dict[str, Any] | None) -> bool:
    """Whether opening a shift with this work type requires field_id.

    Prefer explicit API flags (snake_case or camelCase). If the flag is missing,
    fall back to the same name/category heuristics the backend used for backfill
    so the bot still asks for a field when the API would reject without one.
    """
    if not item:
        return False

    flagged = _coerce_bool(item.get('is_field_work'))
    if flagged is None:
        flagged = _coerce_bool(item.get('isFieldWork'))
    if flagged is True:
        return True

    category = str(item.get('category') or '').lower()
    if 'поле' in category:
        return True

    name = str(item.get('name') or '').strip()
    if name in _FIELD_WORK_NAMES:
        return True

    # Explicit false and no heuristic match
    return False
