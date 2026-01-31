import os, asyncio, logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
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
    await message.answer("✅ Бот работает! Используйте /start чтобы открыть планировщик.")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    """Проверка статуса бота"""
    try:
        await asyncio.to_thread(database.init_db)
        await message.answer("✅ Бот и БД работают! Все системы в норме.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Помощь по командам"""
    help_text = """
🤖 *Доступные команды:*

/start - Открыть планировщик задач
/test - Проверить работу бота
/status - Статус бота и БД
/help - Эта справка
/today - Показать задачи на сегодня

📝 *Как использовать:*
1. Нажмите /start
2. Нажмите кнопку "Открыть планировщик"
3. Добавляйте задачи и напоминания
4. Бот пришлёт напоминания вовремя!

🔔 *Напоминания:*
- Устанавливайте время напоминания
- Бот отправит сообщение точно в срок
- Напоминания приходят как обычные сообщения
    """
    await message.answer(help_text)

@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    """Показать задачи на сегодня"""
    try:
        user_id = message.from_user.id
        today = datetime.now().strftime("%Y-%m-%d")
        
        tasks = await asyncio.to_thread(database.get_tasks_by_user, user_id)
        
        today_tasks = [t for t in tasks if t['date'] == today and not t['completed']]
        
        if not today_tasks:
            await message.answer("🎉 На сегодня задач нет! Можете отдохнуть.")
            return
        
        response = ["📅 *Задачи на сегодня:*\n"]
        
        for i, task in enumerate(today_tasks, 1):
            time_str = f" ({task['time']})" if task['time'] else ""
            status = "🔔" if task['is_reminder'] else "📝"
            response.append(f"{i}. {status} {task['text']}{time_str}")
        
        await message.answer("\n".join(response))
        
    except Exception as e:
        logger.error(f"Ошибка в команде /today: {e}")
        await message.answer("❌ Не удалось получить задачи. Попробуйте позже.")

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
        task_type = data.get('task_type', 'task')
        
        # Для напоминаний проверяем время
        if is_reminder and (not date or not time):
            return web.json_response(
                {"status": "error", "message": "Для напоминания укажите дату и время"},
                status=400
            )
        
        # Сохраняем в БД
        task_id = await asyncio.to_thread(
            database.add_task, 
            user_id, text, date, time, reminder, category, 
            priority, emoji, is_reminder, task_type
        )
        
        if task_id:
            # Отправляем подтверждение пользователю в Telegram
            try:
                if is_reminder:
                    time_str = f" {time}" if time else ""
                    await bot.send_message(
                        user_id,
                        f"✅ Напоминание добавлено!\n\n"
                        f"📝 *{text}*\n"
                        f"📅 *Когда:* {date}{time_str}\n\n"
                        f"Я пришлю вам сообщение точно в срок! 🔔"
                    )
                else:
                    await bot.send_message(
                        user_id,
                        f"✅ Задача добавлена!\n\n"
                        f"📝 *{text}*\n"
                        f"🏷️ *Категория:* {category}"
                    )
            except Exception as e:
                logger.warning(f"Не удалось отправить подтверждение пользователю {user_id}: {e}")
            
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
                        if key == 'time':
                            task[key] = task[key].strftime('%H:%M')
                        elif key == 'date':
                            task[key] = task[key].isoformat()
                        else:
                            task[key] = task[key].isoformat()
            
            return web.json_response({
                "status": "ok",
                "tasks": tasks,
                "count": len(tasks)
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
            # Отправляем уведомление об изменении статуса
            try:
                if completed:
                    await bot.send_message(user_id, f"🎉 Задача выполнена! Так держать!")
                elif deleted:
                    await bot.send_message(user_id, f"🗑️ Задача удалена")
            except:
                pass
            
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
            logger.debug("🔔 Нет напоминаний для отправки")
            return
            
        logger.info(f"🔔 Найдено напоминаний для отправки: {len(tasks)}")
        
        for task in tasks:
            try:
                # Форматируем сообщение
                emoji = task.get('emoji', '🔔')
                time_str = f" ({task['time']})" if task.get('time') else ""
                
                message_text = (
                    f"{emoji} *НАПОМИНАНИЕ!*\n\n"
                    f"📝 *{task['text']}*\n"
                )
                
                if task.get('date'):
                    date_str = datetime.strptime(str(task['date']), "%Y-%m-%d").strftime("%d.%m.%Y")
                    message_text += f"📅 *Когда:* {date_str}{time_str}\n"
                
                message_text += "\n_Сделайте это сейчас!_ ✨"
                
                # Отправляем сообщение
                await bot.send_message(
                    chat_id=task['user_id'],
                    text=message_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Помечаем как отправленное
                await asyncio.to_thread(database.mark_reminder_sent, task['id'])
                logger.info(f"   ✅ Напоминание отправлено user_id={task['user_id']} (задача {task['id']})")
                
            except Exception as e:
                logger.error(f"   ❌ Ошибка отправки напоминания user_id={task.get('user_id')}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

async def archive_overdue_tasks_job():
    """Автоматическая архивация просроченных задач"""
    try:
        archived_count = await asyncio.to_thread(database.archive_overdue_tasks)
        if archived_count > 0:
            logger.info(f"📦 Автоматически архивировано {archived_count} просроченных задач")
    except Exception as e:
        logger.error(f"❌ Ошибка при архивации просроченных задач: {e}")

async def cleanup_old_reminders_job():
    """Очищает старые отправленные напоминания"""
    try:
        cleaned_count = await asyncio.to_thread(database.cleanup_old_reminders)
        if cleaned_count > 0:
            logger.info(f"🧹 Удалено {cleaned_count} старых напоминаний")
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке старых напоминаний: {e}")

# ========== ЗАПУСК И НАСТРОЙКА ==========
async def on_startup():
    """Действия при запуске бота"""
    logger.info("=== Бот запускается ===")
    
    # Инициализируем БД
    await asyncio.to_thread(database.init_db)
    logger.info("✅ База данных инициализирована")
    
    # Запускаем планировщик
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id="reminder_check",
        replace_existing=True
    )
    
    scheduler.add_job(
        archive_overdue_tasks_job,
        'interval',
        hours=1,
        id="archive_check",
        replace_existing=True
    )
    
    scheduler.add_job(
        cleanup_old_reminders_job,
        'interval',
        days=1,
        id="cleanup_check",
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
        return web.Response(text="🤖 TaskFlow Bot is running!")
    
    async def api_info(request):
        return web.json_response({
            "status": "ok",
            "service": "TaskFlow Telegram Bot",
            "version": "2.0",
            "endpoints": {
                "POST /api/new_task": "Добавить новую задачу",
                "GET /api/tasks?user_id=ID": "Получить задачи пользователя",
                "POST /api/update_task": "Обновить задачу"
            },
            "telegram_commands": ["/start", "/help", "/today", "/status", "/test"]
        })
    
    app.router.add_get('/health', health_check)
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
        try:
            await bot.send_message(
                admin_id,
                "🤖 *TaskFlow Bot успешно запущен!*\n\n"
                "✅ База данных инициализирована\n"
                "✅ Планировщик запущен\n"
                "✅ API готово к работе\n"
                f"✅ Webhook: {'установлен' if WEBHOOK_HOST else 'не используется'}\n\n"
                "🚀 Бот готов к работе!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить администратора: {e}")
    
    logger.info("=== Бот успешно запущен ===")
    
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
    
    # Render сам назначает порт через переменную PORT
    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    logger.info(f"🔗 API доступно:")
    logger.info(f"  - POST /api/new_task - Добавить задачу")
    logger.info(f"  - GET  /api/tasks?user_id=ID - Получить задачи")
    logger.info(f"  - POST /api/update_task - Обновить задачу")
    
    # Информация о боте
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот @{bot_info.username} запущен")
    logger.info(f"📱 WebApp URL: {WEB_APP_URL}")
    
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
        asyncio.run(on_shutdown())
