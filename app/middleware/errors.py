"""Log handler errors without crashing the polling loop."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger('agrodesk.bot.errors')

router = Router()


@router.errors()
async def log_handler_error(event: ErrorEvent) -> bool:
    exc = event.exception
    update = event.update
    update_id = getattr(update, 'update_id', '?')
    logger.exception(
        'Handler error update_id=%s: %s',
        update_id,
        exc,
        exc_info=exc,
    )
    return True
