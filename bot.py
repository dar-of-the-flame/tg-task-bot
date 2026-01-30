import os
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from aiohttp import web
import database
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
if not API_TOKEN:
    raise ValueError("Не задан BOT_TOKEN в переменных окружения")

IS_RENDER = os.getenv('RENDER') == 'true'
WEB_APP_URL =  "https://dar-of-the-flame.github.io/tg-task-frontend/"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()
app = web.Application()

# ========== TELEGRAM КОМАНДЫ ==========
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """Отправляем кнопку для открытия Web App."""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    button = types.KeyboardButton(
        text="📋 Открыть планировщик",
        web_app=WebAppInfo(url=WEB_APP_URL)
    )
    keyboard.add(button)
    await message.answer(
        "🚀 Привет! Я твой персональный планировщик задач.\n"
        "Нажми кнопку ниже, чтобы открыть интерфейс и добавить первую задачу с напоминанием!",
        reply_markup=keyboard
    )

@dp.message_handler(commands=['test'])
async def cmd_test(message: types.Message):
    """Тестовая команда для проверки работы бота."""
    await message.answer("✅ Бот работает! Тестовое сообщение.")

# ========== API ДЛЯ FRONTEND ==========
async def handle_new_task(request):
    """Принимает новую задачу от Web App."""
    try:
        data = await request.json()
        logger.info(f"Получены данные: {data}")
        
        # Валидация данных
        required_fields = ['user_id', 'task_text', 'remind_in_minutes']
        for field in required_fields:
            if field not in data:
                return web.json_response(
                    {"status": "error", "message": f"Отсутствует поле: {field}"},
                    status=400
                )
        
        user_id = data['user_id']
        emoji = data.get('emoji', '📌')
        task_text = data['task_text']
        remind_in = int(data['remind_in_minutes'])
        
        # Время начала (опционально)
        start_time = None
        if data.get('start_time'):
            try:
                start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
            except ValueError as e:
                logger.error(f"Ошибка парсинга start_time: {e}")
        
        # Время окончания (опционально)
        end_time = None
        if data.get('end_time'):
            try:
                end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))
            except ValueError as e:
                logger.error(f"Ошибка парсинга end_time: {e}")
        
        # Рассчитываем время напоминания
        if start_time and remind_in > 0:
            remind_at = start_time - timedelta(minutes=remind_in)
        else:
            remind_at = datetime.now() + timedelta(minutes=remind_in)
        
        # Сохраняем в базу
        success = await database.add_task(user_id, emoji, task_text, remind_at, start_time, end_time)
        
        if success:
            return web.json_response({
                "status": "ok", 
                "message": "Задача добавлена",
                "remind_at": remind_at.isoformat()
            })
        else:
            return web.json_response(
                {"status": "error", "message": "Ошибка при сохранении задачи"},
                status=500
            )
            
    except json.JSONDecodeError:
        return web.json_response(
            {"status": "error", "message": "Неверный формат JSON"},
            status=400
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_new_task: {e}")
        return web.json_response(
            {"status": "error", "message": "Внутренняя ошибка сервера"},
            status=500
        )

# ========== ФУНКЦИЯ РАССЫЛКИ НАПОМИНАНИЙ ==========
async def check_and_send_reminders():
    """Эта функция запускается по расписанию каждую минуту."""
    try:
        pending_tasks = await database.get_pending_reminders()
        logger.info(f"Найдено задач для напоминания: {len(pending_tasks)}")
        
        for task in pending_tasks:
            task_id, user_id, emoji, task_text, start_time = task
            
            # Формируем сообщение
            time_info = ""
            if start_time:
                # Приводим к локальному времени
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time)
                time_info = f" в {start_time.strftime('%H:%M')}"
            
            message = f"🔔 {emoji or '📌'} **Напоминание!**\n\n{task_text}{time_info}"
            
            try:
                await bot.send_message(
                    chat_id=user_id, 
                    text=message, 
                    parse_mode="Markdown"
                )
                await database.mark_reminder_sent(task_id)
                logger.info(f"Отправлено напоминание пользователю {user_id}: '{task_text}'")
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка в check_and_send_reminders: {e}")

# ========== ЗАПУСК И НАСТРОЙКА ==========
async def on_startup(_):
    """Действия при запуске бота."""
    logger.info("=== Бот запускается ===")
    
    # 1. Инициализируем базу данных
    try:
        await database.init_db()
        logger.info("База данных инициализирована.")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
    
    # 2. Запускаем планировщик задач
    try:
        scheduler.add_job(
            check_and_send_reminders,
            'interval',
            minutes=1,
            id="reminder_check",
            replace_existing=True
        )
        
        if not scheduler.running:
            scheduler.start()
            logger.info("Планировщик APScheduler запущен (проверка каждую минуту).")
    except Exception as e:
        logger.error(f"Ошибка запуска планировщика: {e}")
    
    # 3. Настраиваем API маршруты
    app.router.add_post('/api/new_task', handle_new_task)
    
    # 4. Простой эндпоинт для проверки здоровья
    async def health_check(request):
        return web.Response(text="Bot is running")
    
    app.router.add_get('/health', health_check)
    
    # 5. Отправляем уведомление администратору (опционально)
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(admin_id, "🤖 Бот планировщика успешно запущен!")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу: {e}")
    
    logger.info("=== Бот успешно запущен ===")

async def on_shutdown(_):
    """Действия при остановке бота."""
    logger.info("Бот останавливается...")
    scheduler.shutdown()
    await bot.session.close()
    logger.info("Бот остановлен.")

if __name__ == '__main__':
    try:
        # Регистрируем обработчики запуска и остановки
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown
        )
        
        # Запускаем aiohttp веб-сервер для API
        # На Render используется порт из переменной окружения PORT
        port = int(os.getenv('PORT', 10000))
        web.run_app(app, port=port, host='0.0.0.0')
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
