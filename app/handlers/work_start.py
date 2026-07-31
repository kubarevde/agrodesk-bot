from datetime import datetime
import logging
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from app.services.api_client import AccessError, ApiClient, access_message, shift_op_user_message
from app.services.dual_writer import DualWriter
from app.states.workday import StartWork
from app.utils.menu import menu_for_user
from app.utils.org_time import now_in_org
from app.utils.references import find_by_name, is_field_work_type

router = Router()
logger = logging.getLogger(__name__)

SKIP_EQUIPMENT = 'Нет / пропустить'
SKIP_AGRO_PLAN = 'Своя работа (без плана)'
_EMPTY_COMMENT_VALUES = frozenset({'нет', 'no', '-'})


def format_dt(dt: datetime) -> str:
    return dt.strftime('%d.%m.%Y ') + str(dt.hour) + dt.strftime(':%M:%S')


def geo_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📍 Отправить геометку', request_location=True)],
            [KeyboardButton(text='⏭ Пропустить')],
            [KeyboardButton(text='❌ Отмена')],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def locations_keyboard(locations: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get('name', '')))] for item in locations if item.get('name')]
    rows.append([KeyboardButton(text='❌ Отмена')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def work_types_keyboard(work_types: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get('name', '')))] for item in work_types if item.get('name')]
    rows.append([KeyboardButton(text='❌ Отмена')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def equipment_keyboard(equipment: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get('name', '')))] for item in equipment if item.get('name')]
    rows.append([KeyboardButton(text=SKIP_EQUIPMENT)])
    rows.append([KeyboardButton(text='❌ Отмена')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def fields_keyboard(fields: list[dict]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=str(item.get('name', '')))] for item in fields if item.get('name')]
    rows.append([KeyboardButton(text='❌ Отмена')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def comment_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Нет')],
            [KeyboardButton(text='❌ Отмена')],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _plan_get(plan: dict, *keys: str) -> Any:
    for key in keys:
        if plan.get(key) is not None:
            return plan.get(key)
    return None


def first_field_name(plan: dict) -> str:
    name = _plan_get(plan, 'field_name', 'fieldName')
    if name:
        return str(name).strip()
    names = _plan_get(plan, 'field_names', 'fieldNames') or []
    if names:
        return str(names[0]).strip()
    return ''


def agro_plan_button_label(plan: dict) -> str:
    work_type = str(
        _plan_get(plan, 'work_type_name', 'workTypeName') or ''
    ).strip()
    field = first_field_name(plan)
    if work_type and field:
        label = f'{work_type} · {field}'
    else:
        label = work_type or field or 'План'
    return label[:60]


def selectable_agro_plans(plans: list[dict]) -> list[dict]:
    selected: list[dict] = []
    for plan in plans:
        status = str(plan.get('status') or '').strip().lower()
        if status in ('', 'planned', 'in_progress'):
            selected.append(plan)
    return selected


def agro_plans_keyboard(plans: list[dict]) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=agro_plan_button_label(plan))]
        for plan in plans
    ]
    rows.append([KeyboardButton(text=SKIP_AGRO_PLAN)])
    rows.append([KeyboardButton(text='❌ Отмена')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def find_plan_by_label(plans: list[dict], text: str) -> dict | None:
    needle = (text or '').strip()
    for plan in plans:
        if agro_plan_button_label(plan) == needle:
            return plan
    return None


def normalize_work_types(work_types: list[dict]) -> list[dict]:
    """Ensure each work type has a reliable boolean is_field_work for FSM/UI."""
    normalized: list[dict] = []
    for item in work_types:
        row = dict(item)
        row['is_field_work'] = is_field_work_type(row)
        normalized.append(row)
    return normalized


def plan_work_type_proxy(plan: dict) -> dict[str, Any]:
    return {
        'name': str(_plan_get(plan, 'work_type_name', 'workTypeName') or ''),
        'is_field_work': _plan_get(plan, 'is_field_work', 'isFieldWork'),
        'isFieldWork': _plan_get(plan, 'isFieldWork', 'is_field_work'),
        'category': _plan_get(plan, 'category'),
    }


async def cancel_flow(message: Message, state: FSMContext, api: ApiClient) -> None:
    await state.clear()
    is_admin = await api.is_admin(message.from_user.id)
    await message.answer('Отменено.', reply_markup=menu_for_user(is_admin))


async def ask_location(message: Message, state: FSMContext, locations: list[dict]) -> None:
    await state.set_state(StartWork.location)
    await message.answer(
        '📍 Где работаешь? Выбери объект:',
        reply_markup=locations_keyboard(locations),
    )


async def prompt_comment(message: Message, state: FSMContext) -> None:
    await state.set_state(StartWork.comment)
    await message.answer(
        '💬 Комментарий к началу смены (или «Нет»):',
        reply_markup=comment_keyboard(),
    )


@router.message(F.text == '🟢 Начал работу')
async def work_start_begin(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    tg_id = message.from_user.id
    access = await api.resolve_access(tg_id)
    if not access.ok:
        error = access.error or AccessError.UNKNOWN
        if error == AccessError.NOT_LINKED:
            await message.answer(
                f'Вы не привязаны к системе.\n'
                f'Сообщите менеджеру ваш Telegram ID: {tg_id}'
            )
        else:
            await message.answer(access_message(error, tg_id))
        return

    employee = access.employee or {}
    is_admin = str(employee.get('role', '')) in ('admin', 'manager')

    active = await api.get_active_shift(tg_id)
    if active:
        await message.answer(
            'Уже есть открытая смена',
            reply_markup=menu_for_user(is_admin),
        )
        return

    locations = await api.get_locations(tg_id)
    if not locations:
        await message.answer(
            '❌ Список объектов пуст.',
            reply_markup=menu_for_user(is_admin),
        )
        return

    start_time_str = format_dt(await now_in_org(api, tg_id))
    await state.update_data(
        _locations=locations,
        employee=employee,
        start_time_str=start_time_str,
        agro_plan_id=None,
        _from_plan=False,
    )

    plans = selectable_agro_plans(await api.get_agro_plans_today(tg_id))
    if plans:
        await state.update_data(_agro_plans=plans)
        await state.set_state(StartWork.agro_plan)
        await message.answer(
            '📋 Есть задачи на сегодня. Выбери план или свою работу:',
            reply_markup=agro_plans_keyboard(plans),
        )
        return

    await ask_location(message, state, locations)


@router.message(StartWork.agro_plan)
async def work_start_agro_plan(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if message.text == '❌ Отмена':
        await cancel_flow(message, state, api)
        return

    data = await state.get_data()
    locations: list[dict] = data.get('_locations') or []
    plans: list[dict] = data.get('_agro_plans') or []
    text = (message.text or '').strip()

    if text == SKIP_AGRO_PLAN:
        await state.update_data(
            agro_plan_id=None,
            work_type_id=None,
            work_type_name=None,
            is_field_work=False,
            field_id=None,
            field_name=None,
            equipment_id=None,
            equipment_name=None,
            implement_id=None,
            _from_plan=False,
        )
        await ask_location(message, state, locations)
        return

    plan = find_plan_by_label(plans, text)
    if not plan:
        await message.answer(
            'Выбери план кнопкой из списка.',
            reply_markup=agro_plans_keyboard(plans),
        )
        return

    work_type_id = _plan_get(plan, 'work_type_id', 'workTypeId')
    work_type_name = str(_plan_get(plan, 'work_type_name', 'workTypeName') or '')
    field_id = _plan_get(plan, 'field_id', 'fieldId')
    field_ids = _plan_get(plan, 'field_ids', 'fieldIds') or []
    if field_id is None and field_ids:
        field_id = field_ids[0]
    field_name = first_field_name(plan) or None
    equipment_id = _plan_get(plan, 'equipment_id', 'equipmentId')
    equipment_name = _plan_get(plan, 'equipment_name', 'equipmentName')
    implement_id = _plan_get(plan, 'implement_id', 'implementId')
    is_field = is_field_work_type(plan_work_type_proxy(plan))

    await state.update_data(
        agro_plan_id=str(plan.get('id')) if plan.get('id') is not None else None,
        work_type_id=str(work_type_id) if work_type_id is not None else None,
        work_type_name=work_type_name,
        is_field_work=is_field,
        field_id=str(field_id) if field_id is not None else None,
        field_name=field_name,
        equipment_id=str(equipment_id) if equipment_id is not None else None,
        equipment_name=str(equipment_name) if equipment_name else None,
        implement_id=str(implement_id) if implement_id is not None else None,
        _from_plan=True,
    )
    await ask_location(message, state, locations)


@router.message(StartWork.location)
async def work_start_location(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if message.text == '❌ Отмена':
        await cancel_flow(message, state, api)
        return

    data = await state.get_data()
    locations: list[dict] = data.get('_locations') or []
    item = find_by_name(locations, message.text or '')
    if not item:
        await message.answer(
            'Выбери объект кнопкой из списка.',
            reply_markup=locations_keyboard(locations),
        )
        return

    await state.update_data(
        location_id=str(item['id']),
        location_name=str(item.get('name', '')),
    )
    await state.set_state(StartWork.geo)
    await message.answer(
        '📍 Отправь геометку или нажми «Пропустить»:',
        reply_markup=geo_keyboard(),
    )


async def continue_after_geo(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    *,
    lat: float | None,
    lng: float | None,
) -> None:
    tg_id = message.from_user.id
    data = await state.get_data()
    await state.update_data(lat=lat, lng=lng)

    if data.get('_from_plan') and data.get('work_type_id'):
        if data.get('is_field_work') and not data.get('field_id'):
            await prompt_field_or_fail(message, state, api, tg_id)
            return
        if data.get('equipment_id'):
            await prompt_comment(message, state)
            return
        await prompt_equipment(message, state, api, tg_id)
        return

    is_admin = await api.is_admin(tg_id)
    work_types = await api.get_work_types(tg_id)
    if not work_types:
        await state.clear()
        await message.answer(
            '❌ Список типов работ пуст.',
            reply_markup=menu_for_user(is_admin),
        )
        return

    work_types = normalize_work_types(work_types)
    await state.update_data(_work_types=work_types)
    await state.set_state(StartWork.work_type)
    await message.answer(
        '🔧 Выбери тип работы:',
        reply_markup=work_types_keyboard(work_types),
    )


@router.message(StartWork.geo, F.location)
async def work_start_geo_location(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    await continue_after_geo(
        message,
        state,
        api,
        lat=float(message.location.latitude),
        lng=float(message.location.longitude),
    )


@router.message(StartWork.geo, F.text == '⏭ Пропустить')
async def work_start_geo_skip(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    await continue_after_geo(message, state, api, lat=None, lng=None)


@router.message(StartWork.geo, F.text == '❌ Отмена')
async def work_start_geo_cancel(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    await cancel_flow(message, state, api)


@router.message(StartWork.geo)
async def work_start_geo_invalid(message: Message) -> None:
    await message.answer(
        'Пожалуйста, отправь геометку кнопкой или нажми «⏭ Пропустить».',
        reply_markup=geo_keyboard(),
    )


@router.message(StartWork.work_type)
async def work_start_type(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if message.text == '❌ Отмена':
        await cancel_flow(message, state, api)
        return

    tg_id = message.from_user.id
    data = await state.get_data()
    work_types: list[dict] = data.get('_work_types') or []
    item = find_by_name(work_types, message.text or '')
    if not item:
        await message.answer(
            'Выбери тип работы кнопкой из списка.',
            reply_markup=work_types_keyboard(work_types),
        )
        return

    is_field = is_field_work_type(item)
    logger.info(
        'work_start type chosen tg_id=%s work_type_id=%s name=%s is_field_work=%s raw_flag=%r',
        tg_id,
        item.get('id'),
        item.get('name'),
        is_field,
        item.get('is_field_work', item.get('isFieldWork')),
    )
    await state.update_data(
        work_type_id=str(item['id']),
        work_type_name=str(item.get('name', '')),
        is_field_work=is_field,
        field_id=None,
        field_name=None,
        agro_plan_id=None,
        _from_plan=False,
    )

    if is_field:
        await prompt_field_or_fail(message, state, api, tg_id)
        return

    await prompt_equipment(message, state, api, tg_id)


async def menu_for_user_safe(api: ApiClient, tg_id: int):
    is_admin = await api.is_admin(tg_id)
    return menu_for_user(is_admin)


async def prompt_field_or_fail(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    tg_id: int,
) -> None:
    fields = await api.get_fields(tg_id)
    if not fields:
        await message.answer(
            'Для полевой работы нужны поля в справочнике. Обратитесь к менеджеру.',
            reply_markup=await menu_for_user_safe(api, tg_id),
        )
        await state.clear()
        return
    await state.update_data(_fields=fields)
    await state.set_state(StartWork.field)
    await message.answer(
        '🌾 Выбери поле:',
        reply_markup=fields_keyboard(fields),
    )


async def prompt_equipment(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    tg_id: int,
) -> None:
    equipment_items = await api.get_equipment(tg_id)
    await state.update_data(_equipment=equipment_items)
    await state.set_state(StartWork.equipment)
    await message.answer(
        '🚜 Выбери технику или нажми «Нет / пропустить»:',
        reply_markup=equipment_keyboard(equipment_items),
    )


@router.message(StartWork.field)
async def work_start_field(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    dual: DualWriter,
) -> None:
    if message.text == '❌ Отмена':
        await cancel_flow(message, state, api)
        return

    tg_id = message.from_user.id
    data = await state.get_data()
    fields: list[dict] = data.get('_fields') or []
    item = find_by_name(fields, message.text or '')
    if not item:
        await message.answer(
            'Выбери поле кнопкой из списка.',
            reply_markup=fields_keyboard(fields),
        )
        return

    await state.update_data(
        field_id=str(item['id']),
        field_name=str(item.get('name', '')),
        _resume_open=False,
    )

    # Recovery after missed field: open with already chosen equipment/comment
    if data.get('_resume_open'):
        await finish_open_shift(message, state, api, dual)
        return

    if data.get('_from_plan') and data.get('equipment_id'):
        await prompt_comment(message, state)
        return

    await prompt_equipment(message, state, api, tg_id)


@router.message(StartWork.equipment)
async def work_start_equipment(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if message.text == '❌ Отмена':
        await cancel_flow(message, state, api)
        return

    data = await state.get_data()
    equipment_items: list[dict] = data.get('_equipment') or []
    text = (message.text or '').strip()

    if text == SKIP_EQUIPMENT:
        await state.update_data(equipment_id=None, equipment_name=None)
    else:
        item = find_by_name(equipment_items, text)
        if not item:
            await message.answer(
                'Выбери технику кнопкой или нажми «Нет / пропустить».',
                reply_markup=equipment_keyboard(equipment_items),
            )
            return
        await state.update_data(
            equipment_id=str(item['id']),
            equipment_name=str(item.get('name', '')),
        )

    await prompt_comment(message, state)


async def finish_open_shift(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    dual: DualWriter,
) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)
    data = await state.get_data()

    employee: dict[str, Any] = dict(data.get('employee') or {})
    if 'employee_name' not in employee and employee.get('full_name'):
        employee['employee_name'] = employee['full_name']

    location_name = str(data.get('location_name') or '')
    work_type_name = str(data.get('work_type_name') or '')
    equipment_name = data.get('equipment_name')
    lat = data.get('lat')
    lng = data.get('lng')
    field_id = data.get('field_id')
    needs_field = bool(data.get('is_field_work'))
    start_comment = str(data.get('start_comment') or '').strip()

    if needs_field and not field_id:
        logger.warning(
            'work_start missing field_id for field work tg_id=%s work_type=%s — re-prompt field',
            tg_id,
            data.get('work_type_id'),
        )
        await state.update_data(_resume_open=True)
        await prompt_field_or_fail(message, state, api, tg_id)
        return

    result = await dual.open_shift(
        tg_id=tg_id,
        location_id=str(data.get('location_id')),
        location_name=location_name,
        work_type_id=str(data.get('work_type_id')),
        work_type_name=work_type_name,
        equipment_id=data.get('equipment_id'),
        equipment_name=equipment_name,
        lat=lat,
        lng=lng,
        employee=employee,
        start_time_str=str(data.get('start_time_str') or ''),
        field_id=field_id,
        agro_plan_id=data.get('agro_plan_id'),
        start_comment=start_comment or None,
    )

    if (
        not result.ok
        and result.detail
        and 'укажите поле' in result.detail.lower()
    ):
        logger.warning(
            'API requires field for work_type=%s — prompting field step',
            data.get('work_type_id'),
        )
        await state.update_data(
            is_field_work=True,
            field_id=None,
            field_name=None,
            _resume_open=True,
        )
        await prompt_field_or_fail(message, state, api, tg_id)
        return

    await state.clear()

    if result.ok:
        geo_info = 'есть' if lat is not None and lng is not None else 'нет'
        field_line = ''
        field_name = data.get('field_name')
        if field_name:
            field_line = f'\n🌾 {field_name}'
        plan_line = '\n📋 По плану' if data.get('agro_plan_id') else ''
        comment_line = f'\n💬 {start_comment}' if start_comment else ''
        await message.answer(
            f'✅ Начало работы зафиксировано!\n'
            f'📍 {location_name}\n'
            f'🔧 {work_type_name}{field_line}{plan_line}\n'
            f'🚜 {equipment_name or "—"}\n'
            f'📌 Геометка: {geo_info}{comment_line}',
            reply_markup=menu_for_user(is_admin),
        )
        return

    await message.answer(
        shift_op_user_message(result, action='открыть'),
        reply_markup=menu_for_user(is_admin),
    )


@router.message(StartWork.comment)
async def work_start_comment(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    dual: DualWriter,
) -> None:
    if message.text == '❌ Отмена':
        await cancel_flow(message, state, api)
        return

    text = (message.text or '').strip()
    start_comment = '' if text.lower() in _EMPTY_COMMENT_VALUES else text
    await state.update_data(start_comment=start_comment)
    await finish_open_shift(message, state, api, dual)
