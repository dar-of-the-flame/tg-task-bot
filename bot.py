import os, asyncio, logging
from datetime import datetime, timedelta
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
@@ -9,13 +9,17 @@
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import database
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')  # Получаем адрес Render.com
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
@@ -325,7 +329,6 @@ async def check_and_send_reminders():
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

# ========== ФУНКЦИЯ АРХИВАЦИИ ПРОСРОЧЕННЫХ ЗАДАЧ ==========
async def archive_overdue_tasks_job():
    """Автоматическая архивация просроченных задач"""
    try:
@@ -335,7 +338,6 @@ async def archive_overdue_tasks_job():
    except Exception as e:
        logger.error(f"❌ Ошибка при архивации просроченных задач: {e}")

# ========== ОЧИСТКА СТАРЫХ НАПОМИНАНИЙ ==========
async def cleanup_old_reminders_job():
    """Очищает старые отправленные напоминания"""
    try:
@@ -355,7 +357,6 @@ async def on_startup():
    logger.info("✅ База данных инициализирована")

    # Запускаем планировщик
    # 1. Проверка напоминаний каждую минуту
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
@@ -364,7 +365,6 @@ async def on_startup():
        replace_existing=True
    )

    # 2. Архивация просроченных задач каждый час
    scheduler.add_job(
        archive_overdue_tasks_job,
        'interval',
@@ -373,7 +373,6 @@ async def on_startup():
        replace_existing=True
    )

    # 3. Очистка старых напоминаний раз в день
    scheduler.add_job(
        cleanup_old_reminders_job,
        'interval',
@@ -411,6 +410,25 @@ async def api_info(request):
    app.router.add_get('/', api_info)
    app.router.add_get('/api', api_info)

    # Настраиваем webhook для Telegram
    if WEBHOOK_HOST:
        # Устанавливаем webhook
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"🌐 Webhook установлен: {WEBHOOK_URL}")
        
        # Создаем обработчик для webhook
        webhook_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=API_TOKEN
        )
        
        # Добавляем маршрут для webhook
        webhook_handler.register(app, path=WEBHOOK_PATH)
        logger.info(f"📡 Webhook маршрут зарегистрирован: {WEBHOOK_PATH}")
    else:
        logger.warning("⚠️ WEBHOOK_HOST не указан, работаем без webhook")
    
    # Уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
@@ -421,7 +439,7 @@ async def api_info(request):
                "✅ База данных инициализирована\n"
                "✅ Планировщик запущен\n"
                "✅ API готово к работе\n"
                "✅ Напоминания будут отправляться вовремя\n\n"
                f"✅ Webhook: {'установлен' if WEBHOOK_HOST else 'не используется'}\n\n"
                "🚀 Бот готов к работе!",
                parse_mode=ParseMode.MARKDOWN
            )
@@ -433,10 +451,26 @@ async def api_info(request):
    # Сразу проверяем напоминания
    await check_and_send_reminders()

async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("=== Остановка бота ===")
    
    # Удаляем webhook
    if WEBHOOK_HOST:
        await bot.delete_webhook()
        logger.info("🌐 Webhook удален")
    
    # Останавливаем планировщик
    scheduler.shutdown()
    logger.info("✅ Планировщик остановлен")

async def main():
    """Основная функция запуска"""
    await on_startup()

    # Настраиваем aiohttp приложение
    setup_application(app, dp, bot=bot)
    
    # Запускаем aiohttp сервер
    runner = web.AppRunner(app)
    await runner.setup()
@@ -457,15 +491,22 @@ async def main():
    logger.info(f"🤖 Бот @{bot_info.username} запущен")
    logger.info(f"📱 WebApp URL: {WEB_APP_URL}")

    # Запускаем бота (он будет работать вечно)
    logger.info("🔄 Запускаем long-polling бота...")
    await dp.start_polling(bot)
    # Запускаем бота в режиме webhook
    if WEBHOOK_HOST:
        logger.info("📡 Работаем в режиме webhook")
        # Бот будет работать через webhook, просто держим сервер запущенным
        await asyncio.Event().wait()
    else:
        logger.warning("⚠️ Работаем без webhook (режим long-polling)")
        # Если нет webhook, используем long-polling (для локальной разработки)
        await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Бот остановлен пользователем")
        asyncio.run(on_shutdown())
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise
        asyncio.run(on_shutdown())
