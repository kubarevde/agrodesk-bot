import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramServerError
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.handlers import start, work_start, work_end, status, admin
from app.middleware.errors import router as errors_router
from app.services.api_client import ApiClient
from app.services.dual_writer import DualWriter

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('agrodesk.bot')

POLLING_BACKOFF_INITIAL = 3
POLLING_BACKOFF_MAX = 120


async def _startup_api_check(api_client: ApiClient) -> None:
    ok, detail = await api_client.health_check()
    if ok:
        logger.info('AgroDesk API health: %s', detail)
        return
    logger.error(
        'AgroDesk API unreachable at startup (%s). Bot will keep running; '
        'users will see a connection error until API is available.',
        detail,
    )


async def _run_polling(dp: Dispatcher, bot: Bot) -> None:
    """Long-polling with exponential backoff on Telegram network errors."""
    backoff = POLLING_BACKOFF_INITIAL
    while True:
        try:
            logger.info(
                'Long-polling started (telegram_timeout=%.0fs, polling_timeout=%ss)',
                settings.telegram_timeout,
                settings.polling_timeout,
            )
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                polling_timeout=settings.polling_timeout,
            )
            logger.info('Polling stopped cleanly')
            return
        except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError) as exc:
            logger.error(
                'Telegram API temporary error (%s) — reconnect in %ss',
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, POLLING_BACKOFF_MAX)
        except Exception:
            logger.exception('Polling crashed — restart in %ss', backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, POLLING_BACKOFF_MAX)


async def main() -> None:
    logger.info('Starting AgroDesk bot env=%s', settings.agrodesk_env)
    logger.info('API_BASE_URL=%s', settings.api_base_url)
    logger.info('BOT_RUN_MODE=%s (bothost.ru: polling)', settings.run_mode)
    logger.info(
        'HTTP timeout=%.1fs retries=%s telegram_timeout=%.0fs sheets_mirror=%s',
        settings.request_timeout,
        settings.request_retries,
        settings.telegram_timeout,
        settings.sheets_mirror_enabled,
    )

    api_client = ApiClient()
    await _startup_api_check(api_client)

    sheets_client = None
    if settings.sheets_mirror_enabled:
        try:
            from app.services.sheets import SheetsClient

            sheets_client = SheetsClient.from_service_account()
            logger.info('Google Sheets mirror: ENABLED')
        except Exception as exc:
            logger.warning('Google Sheets mirror: DISABLED (%s)', exc)

    dual = DualWriter(api_client, sheets_client)

    session = AiohttpSession(timeout=settings.telegram_timeout)
    bot = Bot(token=settings.bot_token, session=session)
    dp = Dispatcher(storage=MemoryStorage())

    dp['api'] = api_client
    dp['sheets'] = sheets_client
    dp['dual'] = dual

    dp.include_router(errors_router)
    dp.include_router(start.router)
    dp.include_router(work_start.router)
    dp.include_router(work_end.router)
    dp.include_router(status.router)
    dp.include_router(admin.router)

    if settings.run_mode == 'webhook':
        logger.error('Webhook mode is not supported — using polling')

    logger.info('AgroDesk Bot ready')
    try:
        await _run_polling(dp, bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
