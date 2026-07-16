from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Начал работу"), KeyboardButton(text="🔴 Закончил работу")],
            [KeyboardButton(text="📊 Мой статус"), KeyboardButton(text="📅 Сегодня")],
        ],
        resize_keyboard=True,
    )


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🟢 Начал работу'), KeyboardButton(text='🔴 Закончил работу')],
            [KeyboardButton(text='📊 Мой статус'), KeyboardButton(text='📅 Сегодня')],
            [KeyboardButton(text='📝 Добавить смену за сотрудника')],
            [KeyboardButton(text='✅ Закрыть смену за сотрудника')],
            [KeyboardButton(text='👥 Кто на смене')],
            [KeyboardButton(text='📊 Дашборд АгроДеск')],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)],
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
