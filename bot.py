import os
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, types, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
import database
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
if not API_TOKEN:
    raise ValueError("Не задан BOT_TOKEN")

WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"  # ЗАМЕНИ НА СВОЙ URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler()
app = web.Application()

# ========== TELEGRAM КОМАНДЫ ==========
@router.message(Command(commands=["start", "help"]))
async def cmd_start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Открыть TaskFlow", web_app=WebAppInfo(url=WEB_APP_URL))]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    await message.answer(
        "🚀 Привет! Я твой планировщик задач.\n"
        "Нажми кнопку ниже, чтобы открыть интерфейс и добавить первую задачу с напоминанием!",
        reply_markup=keyboard
    )

@router.message(Command(commands=["test"]))
async def cmd_test(message: types.Message):
    await message.answer("✅ Бот работает! Тестовое сообщение.")

@router.message(Command(commands=["ping_db"]))
async def cmd_ping_db(message: types.Message):
    try:
        database.init_db()
        await message.answer("✅ Подключение к БД в порядке!")
    except Exception as e:
        await message.answer(f"❌ Ошибка БД: {str(e)[:200]}")

# ========== API ДЛЯ FRONTEND ==========
async def handle_api_new_task(request):
    try:
        data = await request.json()
        logger.info(f"📥 Получена задача: {data}")
        
        required = ['user_id', 'task_text', 'remind_in_minutes']
        if not all(key in data for key in required):
            return web.json_response(
                {"status": "error", "message": "Не хватает полей"},
                status=400
            )
        
        user_id = int(data['user_id'])
        emoji = data.get('emoji', '📌')
        task_text = data['task_text']
        remind_in = int(data['remind_in_minutes'])
        
        # Рассчитываем время напоминания
        if data.get('start_time'):
            start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
            remind_at = start_time - timedelta(minutes=remind_in)
        else:
            start_time = None
            remind_at = datetime.now() + timedelta(minutes=remind_in)
        
        end_time = None
        if data.get('end_time'):
            end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))
        
        task_id = await asyncio.to_thread(
            database.add_task,
            user_id, emoji, task_text, remind_at, start_time, end_time
        )
        
        if task_id:
            return web.json_response({
                "status": "ok",
                "task_id": task_id,
                "remind_at": remind_at.isoformat()
            })
        else:
            return web.json_response(
                {"status": "error", "message": "Ошибка при сохранении в БД"},
                status=500
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка API: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)[:100]},
            status=500
        )

# ========== ФУНКЦИЯ РАССЫЛКИ НАПОМИНАНИЙ ==========
async def check_and_send_reminders():
    try:
        tasks = await asyncio.to_thread(database.get_pending_reminders)
        
        if not tasks:
            return
            
        logger.info(f"🔔 Найдено задач для напоминания: {len(tasks)}")
        
        for task in tasks:
            try:
                time_info = ""
                if task['start_time']:
                    if isinstance(task['start_time'], str):
                        start = datetime.fromisoformat(task['start_time'])
                    else:
                        start = task['start_time']
                    time_info = f" в {start.strftime('%H:%M')}"
                
                message = f"🔔 {task['emoji'] or '📌'} **Напоминание!**\n\n{task['task_text']}{time_info}"
                
                await bot.send_message(
                    chat_id=task['user_id'],
                    text=message
                )
                
                await asyncio.to_thread(database.mark_reminder_sent, task['id'])
                logger.info(f"   ✓ Отправлено user_id={task['user_id']}")
                
            except Exception as e:
                logger.error(f"   ✗ Ошибка отправки user_id={task['user_id']}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

# ========== ЗАПУСК И НАСТРОЙКА ==========
async def on_startup():
    logger.info("=== Бот запускается ===")
    
    # Инициализируем БД
    await asyncio.to_thread(database.init_db)
    
    # Запускаем планировщик
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id="reminder_check",
        replace_existing=True
    )
    scheduler.start()
    logger.info("✅ Планировщик APScheduler запущен")
    
    # Настраиваем API маршруты
    app.router.add_post('/api/new_task', handle_api_new_task)
    
    # Эндпоинты для проверки здоровья
    async def health_check(request):
        return web.Response(text="Bot is running")
    
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    # Уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(admin_id, "🤖 Бот планировщика успешно запущен на aiogram 3.x!")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу: {e}")
    
    logger.info("=== Бот успешно запущен ===")

async def main():
    """Основная функция запуска."""
    await on_startup()
    
    # Запускаем aiohttp сервер в фоне
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 10000)))
    await site.start()
    
    logger.info(f"🌐 Веб-сервер запущен на порту {os.getenv('PORT', 10000)}")
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
