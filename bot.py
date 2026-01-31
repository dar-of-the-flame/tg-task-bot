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

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БОТ ==========
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

dp = Dispatcher()
scheduler = AsyncIOScheduler()
app = web.Application()

# ========== TELEGRAM КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Открыть планировщик", web_app=WebAppInfo(url=WEB_APP_URL))]],
        resize_keyboard=True
    )
    await message.answer("Нажми кнопку ниже, чтобы открыть планировщик задач:", reply_markup=keyboard)

@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    await message.answer("✅ Бот работает!")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    """Проверка статуса бота"""
    try:
        await asyncio.to_thread(database.init_db)
        await message.answer("✅ Бот и БД работают!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

# ========== API ==========
async def api_new_task(request):
    """API для приёма задач от фронтенда"""
    try:
        data = await request.json()
        logger.info(f"📥 Получена задача: {data}")
        
        # Проверяем обязательные поля
        required_fields = ['user_id', 'text']
        for field in required_fields:
            if field not in data:
                return web.json_response(
                    {"status": "error", "message": f"Не хватает {field}"},
                    status=400
                )
        
        # Извлекаем данные
        user_id = int(data['user_id'])
        text = data['text']
        category = data.get('category', 'personal')
        priority = data.get('priority', 'medium')
        date = data.get('date')
        time = data.get('time', '')
        reminder = int(data.get('reminder', 0))
        emoji = data.get('emoji', '📝')
        is_reminder = data.get('is_reminder', False)
        
        # Сохраняем в БД
        task_id = await asyncio.to_thread(
            database.add_task, 
            user_id, text, date, time, reminder, category, priority, emoji, is_reminder
        )
        
        if task_id:
            return web.json_response({
                "status": "ok", 
                "task_id": task_id,
                "message": "Задача добавлена!"
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
        
        try:
            tasks = await asyncio.to_thread(database.get_tasks_by_user, int(user_id))
            
            # Конвертируем datetime в строки
            for task in tasks:
                for key in ['date', 'time', 'created_at', 'completed_at', 'deleted_at', 'remind_at']:
                    if task[key] and hasattr(task[key], 'isoformat'):
                        task[key] = task[key].isoformat()
            
            return web.json_response({
                "status": "ok",
                "tasks": tasks
            })
            
        except Exception as e:
            logger.error(f"❌ Ошибка БД: {e}")
            return web.json_response(
                {"status": "error", "message": "Ошибка БД"},
                status=500
            )
            
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)[:100]},
            status=500
        )

async def api_update_task(request):
    """API для обновления задачи (отметка выполнения, удаление)"""
    try:
        data = await request.json()
        logger.info(f"📥 Обновление задачи: {data}")
        
        task_id = data.get('task_id')
        user_id = data.get('user_id')
        
        if not task_id or not user_id:
            return web.json_response(
                {"status": "error", "message": "Не указаны task_id или user_id"},
                status=400
            )
        
        completed = data.get('completed')
        deleted = data.get('deleted', False)
        archived = data.get('archived')
        
        success = await asyncio.to_thread(
            database.update_task, 
            task_id, int(user_id), completed, deleted, archived
        )
        
        if success:
            return web.json_response({"status": "ok"})
        else:
            return web.json_response(
                {"status": "error", "message": "Ошибка обновления"},
                status=500
            )
        
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)[:100]},
            status=500
        )

# ========== ФУНКЦИЯ РАССЫЛКИ НАПОМИНАНИЙ ==========
async def check_and_send_reminders():
    """Проверяет и отправляет напоминания каждую минуту"""
    try:
        tasks = await asyncio.to_thread(database.get_pending_reminders)
        
        if not tasks:
            return
            
        logger.info(f"🔔 Найдено напоминаний для отправки: {len(tasks)}")
        
        for task in tasks:
            try:
                message = f"🔔 **Напоминание!**\n\n{task['text']}"
                
                await bot.send_message(
                    chat_id=task['user_id'],
                    text=message
                )
                
                await asyncio.to_thread(database.mark_reminder_sent, task['id'])
                logger.info(f"   ✅ Напоминание отправлено user_id={task['user_id']}")
                
            except Exception as e:
                logger.error(f"   ❌ Ошибка отправки напоминания user_id={task['user_id']}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

# ========== ФУНКЦИЯ АРХИВАЦИИ ПРОСРОЧЕННЫХ ЗАДАЧ ==========
async def archive_overdue_tasks_job():
    """Автоматическая архивация просроченных задач"""
    try:
        archived_count = await asyncio.to_thread(database.archive_overdue_tasks)
        if archived_count > 0:
            logger.info(f"📦 Автоматически архивировано {archived_count} просроченных задач")
    except Exception as e:
        logger.error(f"❌ Ошибка при архивации просроченных задач: {e}")

# ========== ЗАПУСК И НАСТРОЙКА ==========
async def on_startup():
    """Действия при запуске бота"""
    logger.info("=== Бот запускается ===")
    
    # Инициализируем БД
    await asyncio.to_thread(database.init_db)
    
    # Запускаем планировщик (проверка каждую минуту)
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id="reminder_check",
        replace_existing=True
    )
    
    # Запускаем задачу архивации просроченных задач (раз в день)
    scheduler.add_job(
        archive_overdue_tasks_job,
        'interval',
        days=1,
        id="archive_check",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("✅ Планировщик APScheduler запущен")
    
    # Настраиваем API маршруты
    app.router.add_post('/api/new_task', api_new_task)
    app.router.add_get('/api/tasks', api_get_tasks)
    app.router.add_post('/api/update_task', api_update_task)
    
    # Эндпоинты для проверки здоровья
    async def health_check(request):
        return web.Response(text="Bot is running")
    
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    # Уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(admin_id, "🤖 Бот планировщика успешно запущен!")
        except:
            pass
    
    logger.info("=== Бот успешно запущен ===")

async def main():
    """Основная функция запуска"""
    await on_startup()
    
    # Запускаем aiohttp сервер
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render сам назначает порт через переменную PORT
    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    logger.info(f"🔗 API доступно:")
    logger.info(f"  - POST /api/new_task")
    logger.info(f"  - GET  /api/tasks?user_id=ID")
    logger.info(f"  - POST /api/update_task")
    
    # Запускаем бота (он будет работать вечно)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise
