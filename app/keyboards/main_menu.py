from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

SHIFTS_BY_DATE_BUTTON = '📅 Смены по дате'
# Keep old label working so redeploy does not break stale keyboards.
SHIFTS_BY_DATE_ALIASES = (SHIFTS_BY_DATE_BUTTON, '📅 Сегодня')


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🟢 Начал работу'), KeyboardButton(text='🔴 Закончил работу')],
            [KeyboardButton(text='📊 Мой статус'), KeyboardButton(text=SHIFTS_BY_DATE_BUTTON)],
        ],
        resize_keyboard=True,
    )


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🟢 Начал работу'), KeyboardButton(text='🔴 Закончил работу')],
            [KeyboardButton(text='📊 Мой статус'), KeyboardButton(text=SHIFTS_BY_DATE_BUTTON)],
            [KeyboardButton(text='📝 Добавить смену за сотрудника')],
            [KeyboardButton(text='✅ Закрыть смену за сотрудника')],
            [KeyboardButton(text='👥 Кто на смене')],
            [KeyboardButton(text='📣 Написать всем')],
            [KeyboardButton(text='📣 Написать кто на смене')],
            [KeyboardButton(text='📊 Дашборд АгроДеск')],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='❌ Отмена')]],
        resize_keyboard=True,
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📍 Отправить геопозицию', request_location=True)],
            [KeyboardButton(text='⏭ Пропустить')],
            [KeyboardButton(text='❌ Отмена')],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
