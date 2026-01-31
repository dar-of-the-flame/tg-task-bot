import os, asyncio, logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
import database
from apscheduler.schedulers.asyncio import AsyncIOScheduler

API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== НАСТРОЙКА ==========
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

dp = Dispatcher()
scheduler = AsyncIOScheduler()
app = web.Application()

# ========== CORS MIDDLEWARE ==========
async def cors_middleware(app, handler):
    async def middleware(request):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response
    return middleware

app.middlewares.append(cors_middleware)

# ========== TELEGRAM КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Открыть", web_app=WebAppInfo(url=WEB_APP_URL))]],
        resize_keyboard=True
    )
    await message.answer("Нажми кнопку ниже:", reply_markup=keyboard)

@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    await message.answer("✅ Бот работает!")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    try:
        await asyncio.to_thread(database.init_db)
        await message.answer("✅ Бот и БД работают!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

# ========== API ЭНДПОИНТЫ ==========
async def api_new_task(request):
    """API для создания новой задачи"""
    try:
        data = await request.json()
        logger.info(f"📥 Получена задача: {data}")
        
        # Валидация
        if 'user_id' not in data or 'text' not in data:
            return web.json_response(
                {"status": "error", "message": "Не хватает user_id или text"},
                status=400
            )
        
        user_id = data['user_id']
        task_text = data['text']
        category = data.get('category', 'personal')
        priority = data.get('priority', 'medium')
        
        # Маппинг категорий на emoji
        emoji_map = {
            'work': '💼',
            'personal': '👤', 
            'health': '❤️',
            'study': '📚'
        }
        emoji = emoji_map.get(category, '📌')
        
        # Обработка времени напоминания
        reminder = data.get('reminder', 0)
        remind_at = datetime.now() + timedelta(minutes=reminder) if reminder > 0 else datetime.now()
        
        # Формирование времени начала
        start_time = None
        if data.get('date'):
            date_str = data['date']
            time_str = data.get('time', '00:00')
            try:
                start_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            except:
                start_time = datetime.now()
        
        # Сохранение в БД
        task_id = await asyncio.to_thread(
            database.add_task, 
            user_id, emoji, task_text, remind_at,
            start_time, None, category, priority
        )
        
        if task_id:
            return web.json_response({
                "status": "ok", 
                "task_id": task_id,
                "message": "Задача сохранена"
            })
        else:
            return web.json_response(
                {"status": "error", "message": "Ошибка сохранения в БД"},
                status=500
            )
            
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)[:100]},
            status=500
        )

async def api_get_tasks(request):
    """API для получения задач пользователя"""
    try:
        user_id = request.query.get('user_id')
        if not user_id:
            return web.json_response(
                {"status": "error", "message": "Не указан user_id"},
                status=400
            )
        
        # Получаем задачи из БД
        tasks = await asyncio.to_thread(database.get_user_tasks, user_id)
        
        logger.info(f"📤 Отправлено задач для user_id={user_id}: {len(tasks)}")
        
        return web.json_response({
            "status": "ok",
            "tasks": tasks,
            "count": len(tasks)
        })
            
    except Exception as e:
        logger.error(f"❌ API get_tasks error: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)[:100]},
            status=500
        )

# ========== СЛУЖЕБНЫЕ ЭНДПОИНТЫ ==========
async def health_check(request):
    """Проверка здоровья сервера"""
    try:
        # Проверяем подключение к БД
        await asyncio.to_thread(database.get_connection)
        return web.Response(text="Bot is running", status=200)
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return web.Response(text="Bot error", status=500)

async def home_page(request):
    """Главная страница"""
    return web.Response(
        text="TaskFlow Bot API v1.0\n"
             "Endpoints:\n"
             "- POST /api/new_task - создать задачу\n"
             "- GET /api/tasks?user_id=... - получить задачи\n"
             "- GET /health - проверка здоровья",
        status=200
    )

# ========== НАПОМИНАНИЯ ==========
async def check_and_send_reminders():
    """Проверка и отправка напоминаний"""
    try:
        tasks = await asyncio.to_thread(database.get_pending_reminders)
        
        if not tasks:
            return
            
        logger.info(f"🔔 Найдено задач для напоминания: {len(tasks)}")
        
        for task in tasks:
            try:
                message = f"🔔 {task['emoji']} {task['task_text']}"
                
                await bot.send_message(
                    chat_id=task['user_id'],
                    text=message
                )
                
                await asyncio.to_thread(database.mark_reminder_sent, task['id'])
                logger.info(f"   ✅ Отправлено user_id={task['user_id']}")
                
            except Exception as e:
                logger.error(f"   ❌ Ошибка отправки user_id={task['user_id']}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Ошибка в check_and_send_reminders: {e}")

# ========== ЗАПУСК ==========
async def on_startup():
    """Запуск приложения"""
    logger.info("=== Бот запускается ===")
    
    # Инициализация БД
    await asyncio.to_thread(database.init_db)
    
    # Запуск планировщика напоминаний
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id="reminder_check",
        replace_existing=True
    )
    scheduler.start()
    logger.info("✅ Планировщик APScheduler запущен")
    
    # Настройка маршрутов
    app.router.add_post('/api/new_task', api_new_task)
    app.router.add_get('/api/tasks', api_get_tasks)
    app.router.add_get('/health', health_check)
    app.router.add_get('/', home_page)
    
    # Уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(admin_id, "🤖 Бот планировщика успешно запущен!")
        except:
            pass
    
    logger.info("=== Бот успешно запущен ===")

async def main():
    """Основная функция"""
    await on_startup()
    
    # Запуск веб-сервера
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    logger.info(f"🔗 API доступно:")
    logger.info(f"   POST /api/new_task")
    logger.info(f"   GET  /api/tasks?user_id=<id>")
    logger.info(f"   GET  /health")
    
    # Держим приложение запущенным
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("Бот останавливается...")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise
