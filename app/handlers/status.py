from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.main_menu import SHIFTS_BY_DATE_ALIASES, cancel_keyboard
from app.services.api_client import ApiClient
from app.states.workday import ShiftsByDate
from app.utils.geo import build_geo_block
from app.utils.menu import menu_for_user
from app.utils.org_time import now_in_org, today_in_org

router = Router()


class ShiftsQuickDateCallback(CallbackData, prefix='svqd'):
    action: str  # today | yesterday | calendar


class ShiftsDatePickCallback(CallbackData, prefix='svdp'):
    action: str  # ignore | prev | next | current | select
    year: int
    month: int
    day: int


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
    raw = str(start_raw or '')
    if 'T' in raw or (' ' in raw and len(raw) > 10):
        try:
            start_dt = datetime.fromisoformat(raw.replace(' ', 'T').split('+')[0])
        except ValueError:
            pass
    minutes = max(int((now - start_dt).total_seconds() // 60), 0)
    return f'{minutes // 60} ч. {minutes % 60} мин.'


def shift_minutes(shift: dict, *, now: datetime, day: date) -> int:
    """Minutes for report: live elapsed for open, stored/computed for closed."""
    status = str(shift.get('status') or '').lower()
    start_raw = shift.get('start_time')
    end_raw = shift.get('end_time')

    if status == 'open':
        start_dt = parse_time(start_raw, today=day)
        raw = str(start_raw or '')
        if 'T' in raw or (' ' in raw and len(raw) > 10):
            try:
                start_dt = datetime.fromisoformat(raw.replace(' ', 'T').split('+')[0])
            except ValueError:
                pass
        if start_dt is None:
            return 0
        return max(int((now - start_dt).total_seconds() // 60), 0)

    raw = shift.get('duration_raw')
    if raw not in (None, ''):
        try:
            return max(int(float(raw)), 0)
        except (TypeError, ValueError):
            pass

    rounded = shift.get('duration_rounded')
    if rounded not in (None, ''):
        try:
            return max(int(float(rounded) * 60), 0)
        except (TypeError, ValueError):
            pass

    start_dt = parse_time(start_raw, today=day)
    end_dt = parse_time(end_raw, today=day)
    if start_dt is None or end_dt is None:
        return 0
    return max(int((end_dt - start_dt).total_seconds() // 60), 0)


def format_hm(total_minutes: int) -> str:
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f'{hours} ч. {mins} мин.'


def format_shift_card(shift: dict, *, now: datetime, day: date) -> str:
    location = shift.get('location') or shift.get('location_name') or '—'
    work_type = shift.get('work_type') or shift.get('work_type_name') or '—'
    equipment = shift.get('equipment') or shift.get('equipment_name') or '—'
    field = shift.get('field_name') or ''
    start = format_clock(shift.get('start_time'))
    status = str(shift.get('status') or '').lower()
    minutes = shift_minutes(shift, now=now, day=day)

    if status == 'open':
        status_text = '🟢 На смене'
        end_text = 'сейчас'
    else:
        status_text = '✅ Закрыта'
        end_raw = shift.get('end_time')
        end_text = format_clock(end_raw) if end_raw else '—'

    geo_text = 'есть' if shift.get('latitude') not in (None, '') and shift.get('longitude') not in (None, '') else 'нет'
    description = str(shift.get('description') or '').strip()
    comment = str(shift.get('comment') or '').strip()

    lines = [
        f'📍 Объект: {location}',
        f'🔧 Тип: {work_type}',
        f'🚜 Техника: {equipment or "—"}',
    ]
    if field:
        lines.append(f'🌾 Поле: {field}')
    lines.extend(
        [
            f'🕐 {start} → {end_text}',
            f'⏱ {format_hm(minutes)}',
            status_text,
            f'📌 Геометка: {geo_text}',
        ]
    )
    if description:
        lines.append(f'📝 Описание: {description}')
    if comment:
        lines.append(f'💬 Комментарий: {comment}')
    return '\n'.join(lines)


def shifts_quick_date_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='Сегодня', callback_data=ShiftsQuickDateCallback(action='today'))
    builder.button(text='Вчера', callback_data=ShiftsQuickDateCallback(action='yesterday'))
    builder.button(
        text='📅 Выбрать дату',
        callback_data=ShiftsQuickDateCallback(action='calendar'),
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def shifts_month_calendar_keyboard(year: int, month: int):
    import calendar

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f'{calendar.month_name[month]} {year}',
        callback_data=ShiftsDatePickCallback(action='ignore', year=year, month=month, day=0),
    )
    for wd in ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']:
        builder.button(
            text=wd,
            callback_data=ShiftsDatePickCallback(action='ignore', year=year, month=month, day=0),
        )

    for week in calendar.monthcalendar(year, month):
        for day_num in week:
            if day_num == 0:
                builder.button(
                    text=' ',
                    callback_data=ShiftsDatePickCallback(
                        action='ignore', year=year, month=month, day=0
                    ),
                )
            else:
                builder.button(
                    text=str(day_num),
                    callback_data=ShiftsDatePickCallback(
                        action='select', year=year, month=month, day=day_num
                    ),
                )

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    today = date.today()
    builder.button(
        text='◀️',
        callback_data=ShiftsDatePickCallback(
            action='prev', year=prev_year, month=prev_month, day=1
        ),
    )
    builder.button(
        text='Сегодня',
        callback_data=ShiftsDatePickCallback(
            action='current', year=today.year, month=today.month, day=today.day
        ),
    )
    builder.button(
        text='▶️',
        callback_data=ShiftsDatePickCallback(
            action='next', year=next_year, month=next_month, day=1
        ),
    )
    builder.adjust(1, 7, 7, 7, 7, 7, 7, 1, 3)
    return builder.as_markup()


def format_shifts_report(
    shifts: list[dict],
    *,
    target: date,
    is_admin: bool,
    now: datetime,
) -> str:
    if is_admin:
        title = f'📅 Все смены за {target.strftime("%d.%m.%Y")}'
    else:
        title = f'📅 Ваши смены за {target.strftime("%d.%m.%Y")}'

    if not shifts:
        return f'{title}\n\nСмен не найдено.'

    total_minutes = 0
    blocks: list[str] = []

    if is_admin:
        employee_blocks: dict[str, list[str]] = {}
        employee_totals: dict[str, int] = {}
        # Preserve first-seen order of employees
        employee_order: list[str] = []

        for shift in shifts:
            name = str(
                shift.get('employee_name') or shift.get('full_name') or '—'
            ).strip() or '—'
            minutes = shift_minutes(shift, now=now, day=target)
            total_minutes += minutes
            if name not in employee_blocks:
                employee_blocks[name] = []
                employee_order.append(name)
                employee_totals[name] = 0
            employee_totals[name] += minutes
            employee_blocks[name].append(format_shift_card(shift, now=now, day=target))

        for name in employee_order:
            blocks.append(
                f'👤 {name}\n\n'
                + '\n\n'.join(employee_blocks[name])
                + f'\n\nИтого по сотруднику: {format_hm(employee_totals[name])}'
            )
    else:
        for shift in shifts:
            minutes = shift_minutes(shift, now=now, day=target)
            total_minutes += minutes
            blocks.append(format_shift_card(shift, now=now, day=target))

    return (
        title
        + '\n\n'
        + '\n\n'.join(blocks)
        + f'\n\nИтого общий: {format_hm(total_minutes)}'
    )


async def send_shifts_for_date(
    message: Message,
    api: ApiClient,
    tg_id: int,
    target: date,
) -> None:
    is_admin = await api.is_admin(tg_id)
    now = await now_in_org(api, tg_id)
    shifts = await api.get_shifts_for_date(tg_id, target.isoformat())
    text = format_shifts_report(
        shifts, target=target, is_admin=is_admin, now=now
    )
    if len(text) <= 4000:
        await message.answer(text, reply_markup=menu_for_user(is_admin))
        return
    chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)]
    for i, chunk in enumerate(chunks):
        markup = menu_for_user(is_admin) if i == len(chunks) - 1 else None
        await message.answer(chunk, reply_markup=markup)


@router.message(F.text == '📊 Мой статус')
async def my_status(message: Message, api: ApiClient) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)
    employee = await api.get_employee(tg_id)
    code = (employee or {}).get('employee_code') or ''
    active = await api.get_active_shift(tg_id)
    if not active:
        who = f' ({code})' if code else ''
        await message.answer(
            f'ℹ️ Активной смены нет{who}.\n'
            'Нажмите «🟢 Начал работу», чтобы открыть смену (нужен интернет).',
            reply_markup=menu_for_user(is_admin),
        )
        return

    location = active.get('location') or active.get('location_name') or '—'
    work_type = active.get('work_type') or active.get('work_type_name') or '—'
    equipment = active.get('equipment') or active.get('equipment_name') or '—'
    field = active.get('field_name') or ''
    start_time = active.get('start_time') or ''
    field_line = f'\n🌾 Поле: {field}' if field else ''
    code_line = f' · {code}' if code else ''
    geo_block = build_geo_block(active)

    await message.answer(
        f'📊 Текущая смена{code_line}\n\n'
        f'📍 Объект: {location}\n'
        f'🔧 Тип: {work_type}\n'
        f'🚜 Техника: {equipment or "—"}{field_line}\n'
        f'🕐 Начало: {format_clock(start_time)}\n'
        f'⏳ Прошло: {await elapsed_label(start_time, api, tg_id)}\n'
        f'{geo_block}',
        reply_markup=menu_for_user(is_admin),
    )


@router.message(F.text.in_(SHIFTS_BY_DATE_ALIASES))
async def shifts_by_date_begin(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)
    await state.set_state(ShiftsByDate.pick)
    await message.answer(
        '📅 Смены по дате\nВыберите день:',
        reply_markup=cancel_keyboard(),
    )
    await message.answer(
        'Сегодня, вчера или календарь:',
        reply_markup=shifts_quick_date_keyboard(),
    )
    # Keep admin/employee menu available after cancel only; inline for pick
    _ = is_admin


@router.message(ShiftsByDate.pick, F.text == '❌ Отмена')
async def shifts_by_date_cancel(message: Message, state: FSMContext, api: ApiClient) -> None:
    await state.clear()
    is_admin = await api.is_admin(message.from_user.id)
    await message.answer('Отменено.', reply_markup=menu_for_user(is_admin))


@router.callback_query(ShiftsQuickDateCallback.filter())
async def shifts_quick_date(
    callback: CallbackQuery,
    callback_data: ShiftsQuickDateCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    tg_id = callback.from_user.id
    org_today = await today_in_org(api, tg_id)

    if callback_data.action == 'calendar':
        await callback.message.edit_text(
            'Выберите дату в календаре:',
            reply_markup=shifts_month_calendar_keyboard(org_today.year, org_today.month),
        )
        await callback.answer()
        return

    if callback_data.action == 'today':
        target = org_today
    elif callback_data.action == 'yesterday':
        target = org_today - timedelta(days=1)
    else:
        target = org_today

    await state.clear()
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_shifts_for_date(callback.message, api, tg_id, target)


@router.callback_query(ShiftsDatePickCallback.filter())
async def shifts_calendar_pick(
    callback: CallbackQuery,
    callback_data: ShiftsDatePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    tg_id = callback.from_user.id

    if callback_data.action == 'ignore':
        await callback.answer()
        return

    if callback_data.action in ('prev', 'next'):
        await callback.message.edit_reply_markup(
            reply_markup=shifts_month_calendar_keyboard(
                callback_data.year, callback_data.month
            )
        )
        await callback.answer()
        return

    if callback_data.action == 'current':
        org_today = await today_in_org(api, tg_id)
        selected = org_today
    elif callback_data.action == 'select':
        selected = date(callback_data.year, callback_data.month, callback_data.day)
    else:
        await callback.answer()
        return

    await state.clear()
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_shifts_for_date(callback.message, api, tg_id, selected)
