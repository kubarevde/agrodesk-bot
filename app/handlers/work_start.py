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


def normalize_work_types(work_types: list[dict]) -> list[dict]:
    """Ensure each work type has a reliable boolean is_field_work for FSM/UI."""
    normalized: list[dict] = []
    for item in work_types:
        row = dict(item)
        row['is_field_work'] = is_field_work_type(row)
        normalized.append(row)
    return normalized


async def cancel_flow(message: Message, state: FSMContext, api: ApiClient) -> None:
    await state.clear()
    is_admin = await api.is_admin(message.from_user.id)
    await message.answer('Отменено.', reply_markup=menu_for_user(is_admin))


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
    )
    await state.set_state(StartWork.location)
    await message.answer(
        '📍 Где работаешь? Выбери объект:',
        reply_markup=locations_keyboard(locations),
    )


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


@router.message(StartWork.geo, F.location)
async def work_start_geo_location(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    tg_id = message.from_user.id
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
    await state.update_data(
        lat=float(message.location.latitude),
        lng=float(message.location.longitude),
        _work_types=work_types,
    )
    await state.set_state(StartWork.work_type)
    await message.answer(
        '🔧 Выбери тип работы:',
        reply_markup=work_types_keyboard(work_types),
    )


@router.message(StartWork.geo, F.text == '⏭ Пропустить')
async def work_start_geo_skip(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    tg_id = message.from_user.id
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
    await state.update_data(lat=None, lng=None, _work_types=work_types)
    await state.set_state(StartWork.work_type)
    await message.answer(
        '🔧 Выбери тип работы:',
        reply_markup=work_types_keyboard(work_types),
    )


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

    await state.set_state(StartWork.comment)
    await message.answer(
        '💬 Комментарий к началу смены (или «Нет»):',
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text='Нет')],
                [KeyboardButton(text='❌ Отмена')],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


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
        await message.answer(
            f'✅ Начало работы зафиксировано!\n'
            f'📍 {location_name}\n'
            f'🔧 {work_type_name}{field_line}\n'
            f'🚜 {equipment_name or "—"}\n'
            f'📌 Геометка: {geo_info}',
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

    await finish_open_shift(message, state, api, dual)
