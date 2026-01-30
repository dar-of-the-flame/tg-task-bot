import os, asyncio, logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from aiohttp import web
import database  # наш синхронный database.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"  # Замени на свой URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()
app = web.Application()

# ========== TELEGRAM КОМАНДЫ ==========
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    button = types.KeyboardButton("📋 Открыть TaskFlow", web_app=WebAppInfo(url=WEB_APP_URL))
    keyboard.add(button)
    await message.answer(
        "🚀 Привет! Я твой планировщик задач.\nНажми кнопку ниже, чтобы открыть интерфейс.",
        reply_markup=keyboard
    )

@dp.message_handler(commands=['test'])
async def cmd_test(message: types.Message):
    """Тестовая команда."""
    await message.answer("✅ Бот работает! Проверка связи.")

@dp.message_handler(commands=['ping_db'])
async def cmd_ping_db(message: types.Message):
    """Проверка подключения к БД."""
    try:
        # Пробуем выполнить простой запрос
        import database
        database.init_db()
        await message.answer("✅ Подключение к БД в порядке!")
    except Exception as e:
        await message.answer(f"❌ Ошибка БД: {str(e)[:200]}")

# ========== API ДЛЯ FRONTEND ==========
async def handle_api_new_task(request):
    """Принимает новую задачу от Web App."""
    try:
        data = await request.json()
        logger.info(f"📥 Получена задача: {data}")
        
        # Валидация
        required = ['user_id', 'task_text', 'remind_in_minutes']
        if not all(key in data for key in required):
            return web.json_response({"status": "error", "message": "Не хватает полей"}, status=400)
        
        # Подготовка данных
        user_id = int(data['user_id'])
        emoji = data.get('emoji', '📌')
        task_text = data['task_text']
        remind_in = int(data['remind_in_minutes'])
        
        # Расчёт времени напоминания
        if data.get('start_time'):
            start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
            remind_at = start_time - timedelta(minutes=remind_in)
        else:
            start_time = None
            remind_at = datetime.now() + timedelta(minutes=remind_in)
        
        end_time = None
        if data.get('end_time'):
            end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))
        
        # Сохранение в БД (синхронный вызов в отдельном потоке)
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
            return web.json_response({"status": "error", "message": "Ошибка БД"}, status=500)
            
    except Exception as e:
        logger.error(f"❌ Ошибка API: {e}")
        return web.json_response({"status": "error", "message": str(e)[:100]}, status=500)

# ========== ФУНКЦИЯ РАССЫЛКИ НАПОМИНАНИЙ ==========
async def check_and_send_reminders():
    """Проверяет и отправляет напоминания каждую минуту."""
    try:
        # Получаем задачи из БД (синхронный вызов в отдельном потоке)
        tasks = await asyncio.to_thread(database.get_pending_reminders)
        
        if not tasks:
            return
            
        logger.info(f"🔔 Найдено задач для напоминания: {len(tasks)}")
        
        for task in tasks:
            try:
                # Формируем сообщение
                time_info = ""
                if task['start_time']:
                    if isinstance(task['start_time'], str):
                        start = datetime.fromisoformat(task['start_time'])
                    else:
                        start = task['start_time']
                    time_info = f" в {start.strftime('%H:%M')}"
                
                message = f"🔔 {task['emoji'] or '📌'} **Напоминание!**\n\n{task['task_text']}{time_info}"
                
                # Отправляем в Telegram
                await bot.send_message(
                    chat_id=task['user_id'],
                    text=message,
                    parse_mode="Markdown"
                )
                
                # Помечаем как отправленное (синхронный вызов)
                await asyncio.to_thread(database.mark_reminder_sent, task['id'])
                
                logger.info(f"   ✓ Отправлено user_id={task['user_id']}")
                
            except Exception as e:
                logger.error(f"   ✗ Ошибка отправки user_id={task['user_id']}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

# ========== ЗАПУСК И НАСТРОЙКА ==========
async def on_startup(_):
    """Действия при запуске бота."""
    logger.info("=== Бот запускается ===")
    
    # 1. Инициализируем БД
    await asyncio.to_thread(database.init_db)
    
    # 2. Запускаем планировщик (проверка каждую минуту)
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id="reminder_check",
        replace_existing=True
    )
    scheduler.start()
    logger.info("✅ Планировщик APScheduler запущен")
    
    # 3. Настраиваем API маршруты
    app.router.add_post('/api/new_task', handle_api_new_task)
    
    # 4. Эндпоинт для проверки здоровья (для UptimeRobot)
    async def health_check(request):
        return web.Response(text="Bot is running")
    
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)  # Корневой тоже для проверки
    
    # 5. Уведомление администратору (опционально)
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(admin_id, "🤖 Бот планировщика успешно запущен на Python 3.13!")
        except:
            pass
    
    logger.info("=== Бот успешно запущен ===")

async def on_shutdown(_):
    """Действия при остановке."""
    logger.info("Бот останавливается...")
    scheduler.shutdown()

if __name__ == '__main__':
    # Регистрируем обработчики
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown
    )
    
    # Запускаем веб-сервер для API
    port = int(os.getenv('PORT', 10000))
    web.run_app(app, port=port, host='0.0.0.0')
