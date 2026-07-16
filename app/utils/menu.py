from aiogram.types import ReplyKeyboardMarkup

from app.keyboards.main_menu import admin_menu_keyboard, main_menu_keyboard


def menu_for_user(is_admin: bool) -> ReplyKeyboardMarkup:
    return admin_menu_keyboard() if is_admin else main_menu_keyboard()
