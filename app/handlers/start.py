from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.services.api_client import AccessError, ApiClient, access_message
from app.utils.menu import menu_for_user

router = Router()


@router.message(CommandStart())
async def start(message: Message, api: ApiClient):
    tg_id = message.from_user.id
    access = await api.resolve_access(tg_id)

    if not access.ok:
        error = access.error or AccessError.UNKNOWN
        if error == AccessError.NOT_LINKED:
            await message.answer(
                f'Добро пожаловать в АгроДеск!\n\n'
                f'Вы не привязаны к системе.\n'
                f'Сообщите менеджеру ваш Telegram ID: `{tg_id}`\n\n'
                f'После привязки в веб-панели снова нажмите /start.',
                parse_mode='Markdown',
            )
            return
        await message.answer(access_message(error, tg_id))
        return

    employee = access.employee or {}
    is_admin = str(employee.get('role', '')) in ('admin', 'manager')
    name = employee.get('full_name') or employee.get('employee_code', '')
    await message.answer(
        f'Привет, {name}!\nДобро пожаловать в АгроДеск.\nРоль: {employee.get("role", "—")}',
        reply_markup=menu_for_user(is_admin),
    )
