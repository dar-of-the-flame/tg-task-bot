import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiohttp.web import middleware
import database
from aiohttp import hdrs
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')  # Получаем адрес Render.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler()

# ========== CORS MIDDLEWARE ==========
@middleware
async def cors_middleware(request, handler):
    # Обработка preflight запросов
    if request.method == hdrs.METH_OPTIONS:
        response = web.Response()
    else:
        response = await handler(request)
    
    # Добавляем CORS заголовки
    response.headers.update({
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Credentials': 'true'
    })
    
    return response

# ========== КОМАНДА START ==========
@router.message(Command("start"))
async def start_command(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    logger.info(f"👤 Пользователь {user_id} запустил бота")
    
    # Создаем кнопку для открытия WebApp
    web_app = WebAppInfo(url=f"{WEB_APP_URL}?startapp={user_id}")
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Открыть планировщик", web_app=web_app)]],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    # Также добавляем inline-кнопку
    inline_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть WebApp", web_app=web_app)],
            [InlineKeyboardButton(text="🆔 Мой ID", callback_data=f"userid_{user_id}")]
        ]
    )

    await message.answer(
        f"🎯 *TaskFlow - Умный планировщик задач*\n\n"
        f"Привет, {message.from_user.first_name}!\n\n"
        f"📱 *Твой ID:* `{user_id}`\n"
        f"🔑 *Сохрани этот ID для синхронизации*\n\n"
        f"Нажми кнопку ниже, чтобы открыть планировщик:",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Отправляем второе сообщение с inline-кнопкой
    await message.answer(
        "Или используй эту кнопку:",
        reply_markup=inline_keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

# ========== ПОЛУЧЕНИЕ USER ID ==========
@router.callback_query(F.data.startswith("userid_"))
async def get_user_id(callback: CallbackQuery):
    user_id = callback.data.replace("userid_", "")
    await callback.answer(f"Твой ID: {user_id}", show_alert=True)
    await callback.message.answer(
        f"📋 *Твой User ID:* `{user_id}`\n\n"
        f"Сохрани этот номер. Он нужен для синхронизации задач.",
        parse_mode=ParseMode.MARKDOWN
    )

# ========== КОМАНДА MYID ==========
@router.message(Command("myid"))
async def myid_command(message: Message):
    """Показывает ID пользователя"""
    user_id = message.from_user.id
    await message.answer(
        f"📋 *Твой User ID:* `{user_id}`\n\n"
        f"Сохрани этот номер. Он нужен для синхронизации задач.\n\n"
        f"Используй его в WebApp если будет запрошен.",
        parse_mode=ParseMode.MARKDOWN
    )

# ========== API ДЛЯ ВЕБ-ПРИЛОЖЕНИЯ ==========
@router.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    """Обработка данных из веб-приложения"""
    try:
        data = message.web_app_data.data
        user_id = message.from_user.id
        logger.info(f"📱 Данные от user_id={user_id}: {data}")
        
        # Парсим JSON данные
        import json
        try:
            data_json = json.loads(data)
            logger.info(f"📊 JSON данные: {data_json}")
        except:
            logger.info(f"📊 Текстовые данные: {data}")
        
        await message.answer(
            f"✅ Данные получены\n"
            f"👤 Твой ID: `{user_id}`\n"
            f"📊 Используй этот ID в WebApp",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"❌ Ошибка обработки веб-данных: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")

# ========== HTTP СЕРВЕР ДЛЯ API ==========
app = web.Application(middlewares=[cors_middleware])

# Эндпоинт для проверки здоровья
async def health_check(request):
    return web.json_response({"status": "ok", "time": datetime.now().isoformat()})

# Эндпоинт для получения задач
async def get_tasks(request):
    try:
        user_id = request.query.get('user_id')
        if not user_id:
            return web.json_response({"status": "error", "message": "user_id required"}, status=400)
        
        tasks = database.get_tasks_by_user(int(user_id))
        
        # Преобразуем задачи в JSON-совместимый формат
        tasks_list = []
        for task in tasks:
            task_dict = dict(task)
            # Конвертируем datetime в строку
            for key, value in task_dict.items():
                if isinstance(value, datetime):
                    task_dict[key] = value.isoformat()
                elif isinstance(value, timedelta):
                    task_dict[key] = str(value)
            tasks_list.append(task_dict)
        
        logger.info(f"📊 Отправлено {len(tasks_list)} задач для user_id={user_id}")
        return web.json_response({"status": "ok", "tasks": tasks_list})
    except Exception as e:
        logger.error(f"❌ Ошибка получения задач: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# Эндпоинт для создания задачи
async def create_task(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        logger.info(f"📝 Создание задачи для user_id={user_id}: {data}")
        
        required_fields = ['user_id', 'text']
        for field in required_fields:
            if field not in data:
                return web.json_response({"status": "error", "message": f"{field} required"}, status=400)
        
        task_id = database.add_task(
            user_id=data['user_id'],
            text=data['text'],
            date=data.get('date'),
            time=data.get('time'),
            reminder=data.get('reminder', 0),
            category=data.get('category', 'personal'),
            priority=data.get('priority', 'medium'),
            emoji=data.get('emoji', '📝'),
            is_reminder=data.get('is_reminder', False),
            task_type=data.get('task_type', 'task')
        )
        
        if task_id:
            logger.info(f"✅ Задача {task_id} создана для user_id={user_id}")
            return web.json_response({"status": "ok", "task_id": task_id})
        else:
            logger.error(f"❌ Ошибка создания задачи для user_id={user_id}")
            return web.json_response({"status": "error", "message": "Failed to create task"}, status=500)
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания задачи: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# Эндпоинт для обновления задачи
async def update_task(request):
    try:
        data = await request.json()
        logger.info(f"🔄 Обновление задачи: {data}")
        
        if 'task_id' not in data or 'user_id' not in data:
            return web.json_response({"status": "error", "message": "task_id and user_id required"}, status=400)
        
        success = database.update_task(
            task_id=data['task_id'],
            user_id=data['user_id'],
            updates=data.get('updates', {})
        )
        
        if success:
            return web.json_response({"status": "ok"})
        else:
            return web.json_response({"status": "error", "message": "Task not found or update failed"}, status=404)
            
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# ========== НАПОМИНАНИЯ ==========
async def check_and_send_reminders():
    """Проверяет и отправляет напоминания"""
    try:
        reminders = database.get_pending_reminders()
        
        for reminder in reminders:
            try:
                task_text = reminder['text']
                user_id = reminder['user_id']
                task_id = reminder['id']
                
                # Отправляем напоминание
                await bot.send_message(
                    chat_id=user_id,
                    text=f"🔔 *Напоминание!*\n\n{task_text}\n\n_Время выполнения наступило_",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Помечаем как отправленное
                database.mark_reminder_sent(task_id)
                logger.info(f"✅ Напоминание {task_id} отправлено пользователю {user_id}")
                
                # Небольшая задержка между отправками
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки напоминания {reminder['id']}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_reminders: {e}")

# ========== ФУНКЦИЯ АРХИВАЦИИ ПРОСРОЧЕННЫХ ЗАДАЧ ==========
async def archive_overdue_tasks_job():
    """Автоматическая архивация просроченных задач"""
    try:
        archived_count = database.archive_overdue_tasks()
        if archived_count > 0:
            logger.info(f"📦 Заархивировано {archived_count} просроченных задач")
    except Exception as e:
        logger.error(f"❌ Ошибка при архивации просроченных задач: {e}")

# ========== ОЧИСТКА СТАРЫХ НАПОМИНАНИЙ ==========
async def cleanup_old_reminders_job():
    """Очищает старые отправленные напоминания"""
    try:
        cleaned_count = database.cleanup_old_reminders()
        if cleaned_count > 0:
            logger.info(f"🧹 Очищено {cleaned_count} старых напоминаний")
    except Exception as e:
        logger.error(f"❌ Ошибка очистки старых напоминаний: {e}")

# ========== ЗАПУСК ПРИЛОЖЕНИЯ ==========
async def on_startup():
    """Действия при запуске бота"""
    logger.info("=== Запуск бота ===")
    
    # Инициализируем БД
    database.init_db()
    logger.info("✅ База данных инициализирована")

    # Запускаем планировщик
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id='check_reminders',
        replace_existing=True
    )

    scheduler.add_job(
        archive_overdue_tasks_job,
        'interval',
        hours=1,
        id='archive_tasks',
        replace_existing=True
    )

    scheduler.add_job(
        cleanup_old_reminders_job,
        'interval',
        days=1,
        id='cleanup_reminders',
        replace_existing=True
    )

    scheduler.start()
    logger.info("✅ Планировщик запущен")

    # Регистрируем HTTP маршруты
    app.router.add_get('/health', health_check)
    app.router.add_get('/api/tasks', get_tasks)
    app.router.add_post('/api/new_task', create_task)
    app.router.add_post('/api/update_task', update_task)
    
    # Корневой маршрут
    async def api_info(request):
        return web.json_response({
            "app": "TaskFlow Bot API",
            "status": "running",
            "version": "1.0",
            "endpoints": {
                "GET /health": "Health check",
                "GET /api/tasks?user_id=ID": "Get user tasks",
                "POST /api/new_task": "Create new task",
                "POST /api/update_task": "Update task"
            },
            "webhook": WEBHOOK_URL if WEBHOOK_HOST else "disabled"
        })
    
    app.router.add_get('/', api_info)
    app.router.add_get('/api', api_info)

    # Настраиваем webhook для Telegram
    if WEBHOOK_HOST:
        # Устанавливаем webhook
        try:
            webhook_info = await bot.get_webhook_info()
            logger.info(f"🔄 Текущий webhook: {webhook_info.url}")
            
            if webhook_info.url != WEBHOOK_URL:
                await bot.set_webhook(WEBHOOK_URL, secret_token=API_TOKEN)
                logger.info(f"🌐 Webhook установлен: {WEBHOOK_URL}")
            else:
                logger.info(f"✅ Webhook уже установлен")
                
            # Проверяем webhook
            webhook_info = await bot.get_webhook_info()
            logger.info(f"📊 Информация о webhook:")
            logger.info(f"   URL: {webhook_info.url}")
            logger.info(f"   Ожидает: {webhook_info.pending_update_count}")
            logger.info(f"   Ошибок: {webhook_info.last_error_message}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка настройки webhook: {e}")
        
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
                chat_id=admin_id,
                text="🤖 *TaskFlow Bot запущен*\n\n"
                "✅ База данных инициализирована\n"
                "✅ Планировщик запущен\n"
                "✅ API готово к работе\n"
                f"✅ Webhook: {'установлен' if WEBHOOK_HOST else 'не используется'}\n\n"
                "🚀 Бот готов к работе!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить администратора: {e}")

    # Сразу проверяем напоминания
    await check_and_send_reminders()
    
    logger.info("✅ Бот полностью инициализирован и готов к работе")

async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("=== Остановка бота ===")
    
    # Удаляем webhook
    if WEBHOOK_HOST:
        try:
            await bot.delete_webhook()
            logger.info("🌐 Webhook удален")
        except Exception as e:
            logger.error(f"❌ Ошибка удаления webhook: {e}")
    
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
    
    # Получаем порт из переменной окружения
    port = int(os.getenv('PORT', 8080))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот @{bot_info.username} запущен")
    logger.info(f"📱 WebApp URL: {WEB_APP_URL}")
    logger.info(f"🌐 API доступно по: https://{WEBHOOK_HOST}" if WEBHOOK_HOST else "🌐 API доступно локально")

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
