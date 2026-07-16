import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.main_menu import admin_menu_keyboard, cancel_keyboard
from app.services.api_client import ApiClient
from app.services.dual_writer import DualWriter
from app.states.workday import AdminAddShift, AdminBroadcast, AdminCloseShift

router = Router()
TZ = ZoneInfo("Asia/Bangkok")
SKIP_EQUIPMENT = "Нет / пропустить"


class DatePickCallback(CallbackData, prefix="dp"):
    action: str
    year: int
    month: int
    day: int
    target: str


class TimePickCallback(CallbackData, prefix="tp"):
    hour: int
    minute: int
    target: str


class QuickDateCallback(CallbackData, prefix="qd"):
    action: str
    target: str


def format_dt(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y ") + str(dt.hour) + dt.strftime(":%M:%S")


def parse_dt(value: str) -> datetime:
    value = str(value).strip()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")


def human_dt(value: str) -> str:
    if not value:
        return "—"
    try:
        dt = parse_dt(value)
        return format_dt(dt)
    except Exception:
        return str(value)


def combine_date_time(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0)


def resolve_quick_date(action: str) -> date:
    today = date.today()
    if action == "today":
        return today
    if action == "yesterday":
        return today - timedelta(days=1)
    if action == "tomorrow":
        return today + timedelta(days=1)
    return today


def to_api_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def employee_display_name(emp: dict) -> str:
    return str(emp.get("full_name") or emp.get("employee_name") or "—").strip()


def employee_keyboard(employees: list[dict]) -> ReplyKeyboardMarkup:
    rows = []
    for emp in employees:
        code = str(emp.get("employee_code", "")).strip()
        name = employee_display_name(emp)
        if code and name and name != "—":
            rows.append([KeyboardButton(text=f"{name} [{code}]")])
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def locations_keyboard(locations: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get("name", "")))] for item in locations if item.get("name")]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def work_types_keyboard(work_types: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get("name", "")))] for item in work_types if item.get("name")]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def equipment_keyboard(equipment: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get("name", "")))] for item in equipment if item.get("name")]
    rows.append([KeyboardButton(text=SKIP_EQUIPMENT)])
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def comment_choice_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Нет")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def parse_employee_code_from_button(text: str) -> str:
    text = str(text).strip()
    if "[" in text and text.endswith("]"):
        return text.split("[")[-1].rstrip("]").strip()
    return ""


def find_employee_by_code(employees: list[dict], code: str) -> dict | None:
    needle = (code or "").strip()
    for emp in employees:
        if str(emp.get("employee_code", "")).strip() == needle:
            return emp
    return None


def find_by_name(items: list[dict], name: str) -> dict | None:
    needle = (name or "").strip()
    for item in items:
        if str(item.get("name", "")).strip() == needle:
            return item
    return None


def shift_matches_employee(shift: dict, employee: dict) -> bool:
    emp_id = str(employee.get("id", "") or "").strip()
    emp_code = str(employee.get("employee_code", "") or "").strip()
    shift_emp_id = str(shift.get("employee_id", "") or "").strip()
    shift_code = str(shift.get("employee_code", "") or "").strip()
    if emp_id and shift_emp_id and emp_id == shift_emp_id:
        return True
    if emp_code and shift_code and emp_code == shift_code:
        return True
    return False


def normalize_comment(text: str) -> str:
    value = (text or "").strip()
    if value.lower() in ("нет", "no", "-"):
        return ""
    return value


def quick_date_keyboard(target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data=QuickDateCallback(action="today", target=target))
    builder.button(text="Вчера", callback_data=QuickDateCallback(action="yesterday", target=target))
    builder.button(text="Завтра", callback_data=QuickDateCallback(action="tomorrow", target=target))
    builder.button(text="📅 Другая дата", callback_data=QuickDateCallback(action="calendar", target=target))
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def month_calendar_keyboard(year: int, month: int, target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"{calendar.month_name[month]} {year}",
        callback_data=DatePickCallback(action="ignore", year=year, month=month, day=0, target=target),
    )

    for wd in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
        builder.button(
            text=wd,
            callback_data=DatePickCallback(action="ignore", year=year, month=month, day=0, target=target),
        )

    for week in calendar.monthcalendar(year, month):
        for day_num in week:
            if day_num == 0:
                builder.button(
                    text=" ",
                    callback_data=DatePickCallback(action="ignore", year=year, month=month, day=0, target=target),
                )
            else:
                builder.button(
                    text=str(day_num),
                    callback_data=DatePickCallback(
                        action="select",
                        year=year,
                        month=month,
                        day=day_num,
                        target=target,
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

    builder.button(
        text="◀️",
        callback_data=DatePickCallback(action="prev", year=prev_year, month=prev_month, day=1, target=target),
    )
    builder.button(
        text="Сегодня",
        callback_data=DatePickCallback(
            action="current",
            year=date.today().year,
            month=date.today().month,
            day=date.today().day,
            target=target,
        ),
    )
    builder.button(
        text="▶️",
        callback_data=DatePickCallback(action="next", year=next_year, month=next_month, day=1, target=target),
    )

    builder.adjust(1, 7, 7, 7, 7, 7, 7, 1, 3)
    return builder.as_markup()


def time_keyboard(target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hour in range(0, 24):
        builder.button(
            text=f"{hour:02d}:00",
            callback_data=TimePickCallback(hour=hour, minute=0, target=target),
        )
        builder.button(
            text=f"{hour:02d}:30",
            callback_data=TimePickCallback(hour=hour, minute=30, target=target),
        )
    builder.adjust(4)
    return builder.as_markup()


@router.message(
    F.text == "❌ Отмена",
    (
        AdminAddShift.employee_select,
        AdminAddShift.start_date,
        AdminAddShift.start_time,
        AdminAddShift.end_date,
        AdminAddShift.end_time,
        AdminAddShift.location,
        AdminAddShift.work_type,
        AdminAddShift.equipment,
        AdminAddShift.description,
        AdminAddShift.comment,
        AdminCloseShift.employee_select,
        AdminCloseShift.end_date,
        AdminCloseShift.end_time,
        AdminCloseShift.description,
        AdminCloseShift.comment,
        AdminBroadcast.target_select,
        AdminBroadcast.message_text,
    ),
)
async def admin_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=admin_menu_keyboard())


@router.message(F.text == "👥 Кто на смене")
async def who_is_working(message: Message, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    shifts = await api.get_active_shifts_all(tg_id)
    if not shifts:
        await message.answer(
            "👥 Сейчас нет сотрудников с открытой сменой.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    lines = []
    for row in shifts:
        employee_name = row.get("employee_name") or row.get("full_name") or "—"
        location = row.get("location") or row.get("location_name") or "—"
        work_type = row.get("work_type") or row.get("work_type_name") or "—"
        start_raw = str(row.get("start_time") or "")
        start_time = start_raw[:16] if start_raw else "—"

        lines.append(
            f"👤 {employee_name}\n"
            f"📍 Объект: {location}\n"
            f"🔧 Тип: {work_type}\n"
            f"🕐 Начало: {start_time}"
        )

    await message.answer(
        "👥 Кто сейчас на смене:\n\n" + "\n\n".join(lines),
        reply_markup=admin_menu_keyboard(),
    )


@router.message(F.text == "📊 Дашборд АгроДеск")
async def dashboard_stats(message: Message, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    stats = await api.get_dashboard_stats(tg_id)
    if not stats:
        await message.answer(
            "❌ Не удалось загрузить дашборд.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    active = stats.get("active_shifts_count", 0)
    today_hours = stats.get("today_hours", 0)
    critical = stats.get("critical_inventory_count", 0)
    salary = stats.get("month_salary_total", 0)

    await message.answer(
        f'👥 На смене: {active}\n'
        f'⏱ Часов сегодня: {today_hours}\n'
        f'📦 Критических остатков: {critical}\n'
        f'💰 Фонд ЗП месяц: {salary} руб',
        reply_markup=admin_menu_keyboard(),
    )


@router.message(F.text == "📣 Написать всем")
async def broadcast_all_begin(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    await state.clear()
    await state.update_data(broadcast_target="all")
    await state.set_state(AdminBroadcast.message_text)
    await message.answer(
        "Введите сообщение для всех сотрудников, у кого подключен бот:",
        reply_markup=cancel_keyboard(),
    )


@router.message(F.text == "📣 Написать кто на смене")
async def broadcast_active_begin(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    await state.clear()
    await state.update_data(broadcast_target="active")
    await state.set_state(AdminBroadcast.message_text)
    await message.answer(
        "Введите сообщение для сотрудников, которые сейчас на смене:",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdminBroadcast.message_text)
async def broadcast_send(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    data = await state.get_data()
    target = data.get("broadcast_target")
    text = (message.text or "").strip()

    if not text:
        await message.answer("Сообщение пустое. Введи текст или нажми «❌ Отмена».")
        return

    employees = await api.get_all_employees(tg_id)

    if target == "all":
        recipient_ids = [
            int(emp["telegram_id"])
            for emp in employees
            if emp.get("telegram_id") not in (None, "", 0, "0")
        ]
        title = "📢 Сообщение от администратора"
    else:
        active_shifts = await api.get_active_shifts_all(tg_id)
        active_employee_ids = {
            str(s.get("employee_id") or "").strip()
            for s in active_shifts
            if s.get("employee_id")
        }
        recipient_ids = []
        for emp in employees:
            emp_id = str(emp.get("id") or "").strip()
            if emp_id in active_employee_ids and emp.get("telegram_id") not in (None, "", 0, "0"):
                recipient_ids.append(int(emp["telegram_id"]))
        title = "📢 Сообщение от администратора для сотрудников на смене"

    if not recipient_ids:
        await state.clear()
        await message.answer(
            "❌ Не найдено получателей для рассылки.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    sent_count = 0
    fail_count = 0

    for recipient_tg_id in recipient_ids:
        try:
            await message.bot.send_message(recipient_tg_id, f"{title}\n\n{text}")
            sent_count += 1
        except Exception:
            fail_count += 1

    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена.\n\n"
        f"Отправлено: {sent_count}\n"
        f"Не доставлено: {fail_count}",
        reply_markup=admin_menu_keyboard(),
    )


@router.message(F.text == "📝 Добавить смену за сотрудника")
async def admin_add_shift_begin(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    employees = await api.get_all_employees(tg_id)
    if not employees:
        await message.answer("Список сотрудников пуст.", reply_markup=admin_menu_keyboard())
        return

    await state.clear()
    await state.update_data(_employees=employees)
    await state.set_state(AdminAddShift.employee_select)
    await message.answer("Выбери сотрудника:", reply_markup=employee_keyboard(employees))


@router.message(AdminAddShift.employee_select)
async def admin_add_shift_employee(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    employee_code = parse_employee_code_from_button(message.text or "")
    if not employee_code:
        await message.answer("Выбери сотрудника кнопкой из списка.")
        return

    data = await state.get_data()
    employees: list[dict] = data.get("_employees") or await api.get_all_employees(tg_id)
    employee = find_employee_by_code(employees, employee_code)
    if not employee:
        await message.answer("Сотрудник не найден. Выбери сотрудника кнопкой из списка.")
        return

    locations = await api.get_locations(tg_id)
    if not locations:
        await state.clear()
        await message.answer("❌ Список объектов пуст.", reply_markup=admin_menu_keyboard())
        return

    await state.update_data(employee=employee, _locations=locations)
    await state.set_state(AdminAddShift.location)
    await message.answer("📍 Выбери объект:", reply_markup=locations_keyboard(locations))


@router.message(AdminAddShift.location)
async def admin_add_shift_location(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    data = await state.get_data()
    locations: list[dict] = data.get("_locations") or []
    item = find_by_name(locations, message.text or "")
    if not item:
        await message.answer(
            "Выбери объект кнопкой из списка.",
            reply_markup=locations_keyboard(locations),
        )
        return

    work_types = await api.get_work_types(tg_id)
    if not work_types:
        await state.clear()
        await message.answer("❌ Список типов работ пуст.", reply_markup=admin_menu_keyboard())
        return

    await state.update_data(
        location_id=str(item["id"]),
        location_name=str(item.get("name", "")),
        _work_types=work_types,
    )
    await state.set_state(AdminAddShift.work_type)
    await message.answer("🔧 Выбери тип работы:", reply_markup=work_types_keyboard(work_types))


@router.message(AdminAddShift.work_type)
async def admin_add_shift_work_type(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    data = await state.get_data()
    work_types: list[dict] = data.get("_work_types") or []
    item = find_by_name(work_types, message.text or "")
    if not item:
        await message.answer(
            "Выбери тип работы кнопкой из списка.",
            reply_markup=work_types_keyboard(work_types),
        )
        return

    equipment_items = await api.get_equipment(tg_id)
    await state.update_data(
        work_type_id=str(item["id"]),
        work_type_name=str(item.get("name", "")),
        _equipment=equipment_items,
    )
    await state.set_state(AdminAddShift.equipment)
    await message.answer(
        "🚜 Выбери технику или нажми «Нет / пропустить»:",
        reply_markup=equipment_keyboard(equipment_items),
    )


@router.message(AdminAddShift.equipment)
async def admin_add_shift_equipment(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    text = (message.text or "").strip()
    data = await state.get_data()
    equipment_items: list[dict] = data.get("_equipment") or []

    if text == SKIP_EQUIPMENT:
        equipment_id = None
        equipment_name = ""
    else:
        item = find_by_name(equipment_items, text)
        if not item:
            await message.answer(
                "Выбери технику кнопкой или нажми «Нет / пропустить».",
                reply_markup=equipment_keyboard(equipment_items),
            )
            return
        equipment_id = str(item["id"])
        equipment_name = str(item.get("name", ""))

    await state.update_data(
        equipment_id=equipment_id,
        equipment_name=equipment_name,
    )
    await state.set_state(AdminAddShift.start_date)
    await message.answer("Выбери дату начала:", reply_markup=quick_date_keyboard("add_start"))


@router.callback_query(QuickDateCallback.filter(F.target == "add_start"))
async def admin_add_start_quick_date(
    callback: CallbackQuery,
    callback_data: QuickDateCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    if callback_data.action == "calendar":
        today = date.today()
        await callback.message.edit_text(
            "Выбери дату начала:",
            reply_markup=month_calendar_keyboard(today.year, today.month, "add_start"),
        )
    else:
        selected_date = resolve_quick_date(callback_data.action)
        await state.update_data(start_date_value=selected_date.isoformat())
        await state.set_state(AdminAddShift.start_time)
        await callback.message.edit_text(
            f"Дата начала: {selected_date.strftime('%d.%m.%Y')}\nВыбери время начала:",
            reply_markup=time_keyboard("add_start"),
        )
    await callback.answer()


@router.callback_query(DatePickCallback.filter(F.target == "add_start"))
async def admin_add_start_calendar(
    callback: CallbackQuery,
    callback_data: DatePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    if callback_data.action == "ignore":
        await callback.answer()
        return

    if callback_data.action in ("prev", "next", "current"):
        await callback.message.edit_reply_markup(
            reply_markup=month_calendar_keyboard(callback_data.year, callback_data.month, "add_start")
        )
        await callback.answer()
        return

    if callback_data.action == "select":
        selected_date = date(callback_data.year, callback_data.month, callback_data.day)
        await state.update_data(start_date_value=selected_date.isoformat())
        await state.set_state(AdminAddShift.start_time)
        await callback.message.edit_text(
            f"Дата начала: {selected_date.strftime('%d.%m.%Y')}\nВыбери время начала:",
            reply_markup=time_keyboard("add_start"),
        )
        await callback.answer()


@router.callback_query(TimePickCallback.filter(F.target == "add_start"))
async def admin_add_start_time(
    callback: CallbackQuery,
    callback_data: TimePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    data = await state.get_data()
    start_date_value = date.fromisoformat(data["start_date_value"])
    start_dt = combine_date_time(start_date_value, callback_data.hour, callback_data.minute)

    await state.update_data(
        start_time=format_dt(start_dt),
        start_time_iso=to_api_iso(start_dt),
    )
    await state.set_state(AdminAddShift.end_date)
    await callback.message.edit_text(
        f"Начало: {format_dt(start_dt)}\n\nВыбери дату окончания:",
        reply_markup=quick_date_keyboard("add_end"),
    )
    await callback.answer()


@router.callback_query(QuickDateCallback.filter(F.target == "add_end"))
async def admin_add_end_quick_date(
    callback: CallbackQuery,
    callback_data: QuickDateCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    if callback_data.action == "calendar":
        today = date.today()
        await callback.message.edit_text(
            "Выбери дату окончания:",
            reply_markup=month_calendar_keyboard(today.year, today.month, "add_end"),
        )
    else:
        selected_date = resolve_quick_date(callback_data.action)
        await state.update_data(end_date_value=selected_date.isoformat())
        await state.set_state(AdminAddShift.end_time)
        await callback.message.edit_text(
            f"Дата окончания: {selected_date.strftime('%d.%m.%Y')}\nВыбери время окончания:",
            reply_markup=time_keyboard("add_end"),
        )
    await callback.answer()


@router.callback_query(DatePickCallback.filter(F.target == "add_end"))
async def admin_add_end_calendar(
    callback: CallbackQuery,
    callback_data: DatePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    if callback_data.action == "ignore":
        await callback.answer()
        return

    if callback_data.action in ("prev", "next", "current"):
        await callback.message.edit_reply_markup(
            reply_markup=month_calendar_keyboard(callback_data.year, callback_data.month, "add_end")
        )
        await callback.answer()
        return

    if callback_data.action == "select":
        selected_date = date(callback_data.year, callback_data.month, callback_data.day)
        await state.update_data(end_date_value=selected_date.isoformat())
        await state.set_state(AdminAddShift.end_time)
        await callback.message.edit_text(
            f"Дата окончания: {selected_date.strftime('%d.%m.%Y')}\nВыбери время окончания:",
            reply_markup=time_keyboard("add_end"),
        )
        await callback.answer()


@router.callback_query(TimePickCallback.filter(F.target == "add_end"))
async def admin_add_end_time(
    callback: CallbackQuery,
    callback_data: TimePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    data = await state.get_data()
    start_iso = data.get("start_time_iso") or data.get("start_time")
    start_dt = parse_dt(start_iso)
    end_date_value = date.fromisoformat(data["end_date_value"])
    end_dt = combine_date_time(end_date_value, callback_data.hour, callback_data.minute)

    if end_dt <= start_dt:
        await callback.answer("Окончание должно быть позже начала", show_alert=True)
        return

    await state.update_data(
        end_time=format_dt(end_dt),
        end_time_iso=to_api_iso(end_dt),
    )
    await state.set_state(AdminAddShift.description)
    await callback.message.edit_text(
        f"Окончание: {format_dt(end_dt)}\n\nЧто сделал? Краткое описание работы:"
    )
    await callback.message.answer(
        "Что сделал? Краткое описание работы:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminAddShift.description)
async def admin_add_shift_description(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    if not await api.is_admin(message.from_user.id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminAddShift.comment)
    await message.answer("Комментарий (или «нет»):", reply_markup=cancel_keyboard())


@router.message(AdminAddShift.comment)
async def admin_add_shift_comment(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    dual: DualWriter,
) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    data = await state.get_data()
    employee = data["employee"]
    description = str(data.get("description") or "").strip()
    comment_text = normalize_comment(message.text or "")
    full_desc = description if not comment_text else f"{description}\n{comment_text}"

    start_iso = data.get("start_time_iso") or ""
    end_iso = data.get("end_time_iso") or ""

    result = await dual.open_shift_for_employee(
        admin_tg_id=tg_id,
        employee_id=str(employee["id"]),
        employee=employee,
        location_id=str(data.get("location_id") or ""),
        location_name=str(data.get("location_name") or ""),
        work_type_id=str(data.get("work_type_id") or ""),
        work_type_name=str(data.get("work_type_name") or ""),
        equipment_id=data.get("equipment_id"),
        equipment_name=data.get("equipment_name") or None,
        start_time=start_iso,
        end_time=end_iso,
        description=full_desc,
    )

    await state.clear()

    if result:
        await message.answer(
            f"✅ Смена добавлена\n\n"
            f"👤 {employee_display_name(employee)}\n"
            f"📍 {data.get('location_name', '—')}\n"
            f"🔧 {data.get('work_type_name', '—')}\n"
            f"🚜 {data.get('equipment_name') or '—'}\n"
            f"🕐 {human_dt(start_iso)} → {human_dt(end_iso)}",
            reply_markup=admin_menu_keyboard(),
        )
    else:
        await message.answer(
            "❌ Не удалось добавить смену. Проверьте данные и попробуйте снова.",
            reply_markup=admin_menu_keyboard(),
        )


@router.message(F.text == "✅ Закрыть смену за сотрудника")
async def admin_close_shift_begin(message: Message, state: FSMContext, api: ApiClient) -> None:
    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    employees = await api.get_all_employees(tg_id)
    if not employees:
        await message.answer("Список сотрудников пуст.", reply_markup=admin_menu_keyboard())
        return

    await state.clear()
    await state.update_data(_employees=employees)
    await state.set_state(AdminCloseShift.employee_select)
    await message.answer(
        "Выбери сотрудника, чью открытую смену нужно закрыть:",
        reply_markup=employee_keyboard(employees),
    )


@router.message(AdminCloseShift.employee_select)
async def admin_close_shift_employee(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    employee_code = parse_employee_code_from_button(message.text or "")
    if not employee_code:
        await message.answer("Выбери сотрудника кнопкой из списка.")
        return

    data = await state.get_data()
    employees: list[dict] = data.get("_employees") or await api.get_all_employees(tg_id)
    employee = find_employee_by_code(employees, employee_code)
    if not employee:
        await message.answer("Сотрудник не найден.")
        return

    active_shifts = await api.get_active_shifts_all(tg_id)
    open_shift = next((s for s in active_shifts if shift_matches_employee(s, employee)), None)
    if not open_shift:
        await message.answer("У сотрудника нет открытой смены.")
        return

    shift_id = str(open_shift.get("id") or "")
    if not shift_id:
        await message.answer("У сотрудника нет открытой смены.")
        return

    await state.update_data(employee=employee, shift_id=shift_id, open_shift=open_shift)
    await state.set_state(AdminCloseShift.end_date)
    await message.answer("Выбери дату окончания:", reply_markup=quick_date_keyboard("close_end"))


@router.callback_query(QuickDateCallback.filter(F.target == "close_end"))
async def admin_close_end_quick_date(
    callback: CallbackQuery,
    callback_data: QuickDateCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    if callback_data.action == "calendar":
        today = date.today()
        await callback.message.edit_text(
            "Выбери дату окончания:",
            reply_markup=month_calendar_keyboard(today.year, today.month, "close_end"),
        )
    else:
        selected_date = resolve_quick_date(callback_data.action)
        await state.update_data(end_date_value=selected_date.isoformat())
        await state.set_state(AdminCloseShift.end_time)
        await callback.message.edit_text(
            f"Дата окончания: {selected_date.strftime('%d.%m.%Y')}\nВыбери время окончания:",
            reply_markup=time_keyboard("close_end"),
        )
    await callback.answer()


@router.callback_query(DatePickCallback.filter(F.target == "close_end"))
async def admin_close_end_calendar(
    callback: CallbackQuery,
    callback_data: DatePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    if callback_data.action == "ignore":
        await callback.answer()
        return

    if callback_data.action in ("prev", "next", "current"):
        await callback.message.edit_reply_markup(
            reply_markup=month_calendar_keyboard(callback_data.year, callback_data.month, "close_end")
        )
        await callback.answer()
        return

    if callback_data.action == "select":
        selected_date = date(callback_data.year, callback_data.month, callback_data.day)
        await state.update_data(end_date_value=selected_date.isoformat())
        await state.set_state(AdminCloseShift.end_time)
        await callback.message.edit_text(
            f"Дата окончания: {selected_date.strftime('%d.%m.%Y')}\nВыбери время окончания:",
            reply_markup=time_keyboard("close_end"),
        )
        await callback.answer()


@router.callback_query(TimePickCallback.filter(F.target == "close_end"))
async def admin_close_end_time(
    callback: CallbackQuery,
    callback_data: TimePickCallback,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if not await api.is_admin(callback.from_user.id):
        await callback.answer("⛔ Только администратор", show_alert=True)
        return

    data = await state.get_data()
    end_date_value = date.fromisoformat(data["end_date_value"])
    end_dt = combine_date_time(end_date_value, callback_data.hour, callback_data.minute)

    open_shift = data.get("open_shift") or {}
    start_raw = open_shift.get("start_time")
    if start_raw:
        try:
            start_dt = parse_dt(str(start_raw).replace("T", " ")[:19])
            if end_dt <= start_dt:
                await callback.answer("Окончание должно быть позже начала", show_alert=True)
                return
        except ValueError:
            pass

    await state.update_data(
        end_time=format_dt(end_dt),
        end_time_iso=to_api_iso(end_dt),
    )
    await state.set_state(AdminCloseShift.description)
    await callback.message.edit_text(
        f"Окончание: {format_dt(end_dt)}\n\nЧто сделал? Краткое описание работы:"
    )
    await callback.message.answer(
        "Что сделал? Краткое описание работы:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminCloseShift.description)
async def admin_close_shift_description(message: Message, state: FSMContext, api: ApiClient) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    if not await api.is_admin(message.from_user.id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminCloseShift.comment)
    await message.answer("Комментарий к завершению:", reply_markup=comment_choice_keyboard())


@router.message(AdminCloseShift.comment)
async def admin_close_shift_comment(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    dual: DualWriter,
) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_menu_keyboard())
        return

    tg_id = message.from_user.id
    if not await api.is_admin(tg_id):
        await state.clear()
        await message.answer("⛔ Команда доступна только администратору.")
        return

    data = await state.get_data()
    description = str(data.get("description") or "").strip()
    comment_text = normalize_comment(message.text or "")
    full_desc = description if not comment_text else f"{description}\n{comment_text}"
    shift_id = str(data.get("shift_id") or "")
    employee = data.get("employee") or {}
    end_time_str = str(data.get("end_time_iso") or data.get("end_time") or "")

    result = await dual.close_shift_for_employee(
        tg_id,
        shift_id,
        full_desc,
        employee,
        end_time_str,
    )
    await state.clear()

    if result:
        end_display = human_dt(data.get("end_time_iso") or data.get("end_time") or "")
        await message.answer(
            f"✅ Смена закрыта\n\n"
            f"👤 {employee_display_name(employee)}\n"
            f"🕐 Конец: {end_display}",
            reply_markup=admin_menu_keyboard(),
        )
    else:
        await message.answer(
            "❌ Не удалось закрыть смену. Попробуйте снова.",
            reply_markup=admin_menu_keyboard(),
        )
