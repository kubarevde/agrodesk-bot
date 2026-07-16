from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from app.keyboards.main_menu import cancel_keyboard
from app.services.api_client import ApiClient
from app.services.dual_writer import DualWriter
from app.states.workday import EndWork
from app.utils.menu import menu_for_user
from app.utils.org_time import now_in_org

router = Router()


def format_dt(dt: datetime) -> str:
    return dt.strftime('%d.%m.%Y ') + str(dt.hour) + dt.strftime(':%M:%S')


def end_comment_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Нет')],
            [KeyboardButton(text='❌ Отмена')],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


@router.message(F.text == '🔴 Закончил работу')
async def work_end_begin(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)
    active = await api.get_active_shift(tg_id)
    if not active:
        await message.answer(
            'У вас нет открытой смены',
            reply_markup=menu_for_user(is_admin),
        )
        return

    await state.set_state(EndWork.description)
    await message.answer(
        '📝 Что было сделано за смену?',
        reply_markup=cancel_keyboard(),
    )


@router.message(EndWork.description)
async def work_end_description(
    message: Message,
    state: FSMContext,
    api: ApiClient,
) -> None:
    if message.text == '❌ Отмена':
        await state.clear()
        is_admin = await api.is_admin(message.from_user.id)
        await message.answer('Отменено.', reply_markup=menu_for_user(is_admin))
        return

    await state.update_data(description=(message.text or '').strip())
    await state.set_state(EndWork.comment)
    await message.answer(
        '💬 Комментарий к завершению:',
        reply_markup=end_comment_keyboard(),
    )


@router.message(EndWork.comment)
async def work_end_comment(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    dual: DualWriter,
) -> None:
    tg_id = message.from_user.id
    is_admin = await api.is_admin(tg_id)

    if message.text == '❌ Отмена':
        await state.clear()
        await message.answer('Отменено.', reply_markup=menu_for_user(is_admin))
        return

    data = await state.get_data()
    end_time_str = format_dt(await now_in_org(api, tg_id))
    full_desc = str(data.get('description') or '').strip()
    comment = (message.text or '').strip()
    if comment.lower() not in ('нет', 'no', '-'):
        full_desc = f'{full_desc}. {comment}' if full_desc else comment

    if len(full_desc) < 5:
        await message.answer(
            'Описание слишком короткое (минимум 5 символов). '
            'Начните закрытие смены заново: «🔴 Закончил работу».',
            reply_markup=menu_for_user(is_admin),
        )
        await state.clear()
        return

    employee = await api.get_employee(tg_id)
    result = await dual.close_shift(
        tg_id=tg_id,
        description=full_desc,
        employee=employee or {},
        end_time_str=end_time_str,
    )

    await state.clear()

    if result:
        hours = result.get('duration_rounded', 0)
        amount = result.get('calculated_amount')
        amount_text = (
            f'\n💰 Начислено: {int(float(amount))} руб (предварительно)'
            if amount is not None
            else ''
        )
        await message.answer(
            f'✅ Смена закрыта.\n'
            f'⏱ В табель: {hours} ч.\n'
            f'📝 Сделано: {full_desc}{amount_text}',
            reply_markup=menu_for_user(is_admin),
        )
    else:
        await message.answer(
            '❌ Не удалось закрыть смену.',
            reply_markup=menu_for_user(is_admin),
        )
