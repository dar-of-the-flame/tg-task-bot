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
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = f"https://tg-task-bot-service.onrender.com{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
scheduler = AsyncIOScheduler()
app = web.Application()

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
        
        if 'user_id' not in data or 'task_text' not in data:
            return web.json_response(
                {"status": "error", "message": "Не хватает user_id или task_text"},
                status=400
            )
        
        user_id = int(data['user_id'])
        emoji = data.get('emoji', '📌')
        task_text = data['task_text']
        remind_in = int(data.get('remind_in_minutes', 0))
        
        remind_at = datetime.now() + timedelta(minutes=remind_in)
        
        # Добавляем все поля для фронтенда
        task_id = await asyncio.to_thread(
            database.add_task, 
            user_id=user_id,
            emoji=emoji,
            task_text=task_text,
            remind_at=remind_at,
            category=data.get('category', 'personal'),
            priority=data.get('priority', 'medium'),
            date=data.get('date'),
            time=data.get('time', ''),
            completed=data.get('completed', False)
        )
        
        if task_id:
            return web.json_response({
                "status": "ok", 
                "task_id": task_id,
                "message": f"Задача добавлена! Напоминание в {remind_at.strftime('%H:%M')}"
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

# API для получения задач пользователя
async def api_get_tasks(request):
    try:
        user_id = int(request.query.get('user_id', 0))
        if not user_id:
            return web.json_response(
                {"status": "error", "message": "Не указан user_id"},
                status=400
            )
        
        tasks = await asyncio.to_thread(database.get_user_tasks, user_id)
        return web.json_response({
            "status": "ok",
            "tasks": tasks
        })
        
    except Exception as e:
        logger.error(f"❌ API get_tasks error: {e}")
        return web.json_response(
            {"status": "error", "message": str(e)[:100]},
            status=500
        )

# API для обновления задачи
async def api_update_task(request):
    try:
        data = await request.json()
        task_id = data.get('task_id')
        
        if not task_id:
            return web.json_response(
                {"status": "error", "message": "Не указан task_id"},
                status=400
            )
        
        updated = await asyncio.to_thread(
            database.update_task,
            task_id=task_id,
            completed=data.get('completed'),
            deleted=data.get('deleted')
        )
        
        if updated:
            return web.json_response({
                "status": "ok",
                "message": "Задача обновлена"
            })
        else:
            return web.json_response(
                {"status": "error", "message": "Задача не найдена"},
                status=404
            )
            
    except Exception as e:
        logger.error(f"❌ API update_task error: {e}")
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
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

# ========== WEBHOOK HANDLERS ==========
async def handle_webhook(request):
    """Обработчик вебхуков от Telegram"""
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
        return web.Response()
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500)

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
    scheduler.start()
    logger.info("✅ Планировщик APScheduler запущен")
    
    # Настраиваем вебхук
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"🌐 Webhook установлен: {WEBHOOK_URL}")
    
    # Настраиваем API маршруты
    app.router.add_post('/api/new_task', api_new_task)
    app.router.add_get('/api/tasks', api_get_tasks)
    app.router.add_post('/api/update_task', api_update_task)
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    
    # Эндпоинты для проверки здоровья
    async def health_check(request):
        return web.json_response({"status": "ok", "message": "Bot is running"})
    
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
    
    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    logger.info(f"🤖 Бот @{await bot.get_me().username} запущен")
    logger.info(f"📱 WebApp URL: {WEB_APP_URL}")
    logger.info(f"📡 Работаем в режиме webhook")
    
    # Бесконечный цикл (не используем start_polling на Render)
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise
