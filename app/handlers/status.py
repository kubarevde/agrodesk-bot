from datetime import date, datetime

from aiogram import F, Router
from aiogram.types import Message

from app.services.api_client import ApiClient
from app.utils.menu import menu_for_user
from app.utils.org_time import now_in_org, today_in_org

router = Router()


def parse_time(value: object, today: date | None = None) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    day = today or date.today()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            parsed = datetime.strptime(raw[:8] if fmt == '%H:%M:%S' else raw[:5], fmt).time()
            return datetime.combine(day, parsed)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def format_clock(value: object) -> str:
    raw = str(value or '').strip()
    if not raw:
        return '—'
    return raw[:16] if len(raw) >= 16 else raw[:5] if len(raw) >= 5 else raw


async def elapsed_label(start_raw: object, api: ApiClient, tg_id: int) -> str:
    now = await now_in_org(api, tg_id)
    start_dt = parse_time(start_raw, today=now.date())
    if start_dt is None:
        return '0 ч. 0 мин.'
    # parse_time uses today's date; for iso datetime with date keep as-is
    raw = str(start_raw or '')
    if 'T' in raw or ' ' in raw and len(raw) > 10:
        try:
            start_dt = datetime.fromisoformat(raw.replace(' ', 'T').split('+')[0])
        except ValueError:
            pass
    minutes = max(int((now - start_dt).total_seconds() // 60), 0)
    return f'{minutes // 60} ч. {minutes % 60} мин.'


def duration_from_shift(shift: dict) -> tuple[int, int]:
    rounded = shift.get('duration_rounded')
    if rounded is not None:
        total_minutes = int(float(rounded) * 60)
        return total_minutes // 60, total_minutes % 60

    raw = shift.get('duration_raw')
    if raw is not None:
        total_minutes = int(raw)
        return total_minutes // 60, total_minutes % 60

    start_dt = parse_time(shift.get('start_time'))
    end_dt = parse_time(shift.get('end_time'))
    if start_dt is None or end_dt is None:
        return 0, 0
    minutes = max(int((end_dt - start_dt).total_seconds() // 60), 0)
    return minutes // 60, minutes % 60


def status_label(status: object) -> str:
    value = str(status or '').lower()
    if value == 'open':
        return 'открыта'
    if value == 'closed':
        return 'закрыта'
    return str(status or '—')


@router.message(F.text == '📊 Мой статус')
async def my_status(message: Message, api: ApiClient) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)
    active = await api.get_active_shift(tg_id)
    if not active:
        await message.answer(
            'ℹ️ Активной смены нет.',
            reply_markup=menu_for_user(is_admin),
        )
        return

    location = active.get('location') or active.get('location_name') or '—'
    work_type = active.get('work_type') or active.get('work_type_name') or '—'
    equipment = active.get('equipment') or active.get('equipment_name') or '—'
    start_time = active.get('start_time') or ''

    await message.answer(
        f'📍 {location} | 🔧 {work_type} | 🚜 {equipment or "—"}\n'
        f'🕐 Начало: {format_clock(start_time)}  ⏳ Прошло: {await elapsed_label(start_time, api, tg_id)}',
        reply_markup=menu_for_user(is_admin),
    )


@router.message(F.text == '📅 Сегодня')
async def today_info(message: Message, api: ApiClient) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)
    today = (await today_in_org(api, tg_id)).isoformat()
    shifts = await api.get_shifts_for_date(tg_id, today)

    if not shifts:
        await message.answer(
            'За сегодня смен не найдено.',
            reply_markup=menu_for_user(is_admin),
        )
        return

    lines: list[str] = [f'📅 Смены за сегодня ({today})']
    total_minutes = 0

    for shift in shifts:
        hours, minutes = duration_from_shift(shift)
        total_minutes += hours * 60 + minutes

        location = shift.get('location') or shift.get('location_name') or '—'
        work_type = shift.get('work_type') or shift.get('work_type_name') or '—'
        start = format_clock(shift.get('start_time'))
        end_raw = shift.get('end_time')
        end = format_clock(end_raw) if end_raw else '…'
        status = status_label(shift.get('status'))

        prefix = ''
        if is_admin:
            name = shift.get('employee_name') or shift.get('full_name') or '—'
            prefix = f'👤 {name}\n'

        lines.append(
            f'{prefix}'
            f'📍{location} | 🔧{work_type}\n'
            f'| 🕐{start} → {end} | ⏱ {hours}ч {minutes}м | {status}'
        )

    total_h = total_minutes // 60
    total_m = total_minutes % 60
    lines.append(f'\nИтого: {total_h} ч. {total_m} мин.')

    await message.answer(
        '\n\n'.join(lines),
        reply_markup=menu_for_user(is_admin),
    )
