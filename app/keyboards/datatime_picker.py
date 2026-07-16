import calendar
from datetime import date, timedelta

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


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

    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for wd in weekdays:
        builder.button(
            text=wd,
            callback_data=DatePickCallback(action="ignore", year=year, month=month, day=0, target=target),
        )

    for week in calendar.monthcalendar(year, month):
        for day in week:
            if day == 0:
                builder.button(
                    text=" ",
                    callback_data=DatePickCallback(action="ignore", year=year, month=month, day=0, target=target),
                )
            else:
                builder.button(
                    text=str(day),
                    callback_data=DatePickCallback(action="select", year=year, month=month, day=day, target=target),
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
    for hour in range(6, 24):
        builder.button(text=f"{hour:02d}:00", callback_data=TimePickCallback(hour=hour, minute=0, target=target))
        builder.button(text=f"{hour:02d}:30", callback_data=TimePickCallback(hour=hour, minute=30, target=target))
    builder.adjust(4)
    return builder.as_markup()


def resolve_quick_date(action: str) -> date:
    today = date.today()
    if action == "today":
        return today
    if action == "yesterday":
        return today - timedelta(days=1)
    if action == "tomorrow":
        return today + timedelta(days=1)
    return today