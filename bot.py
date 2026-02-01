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
from apscheduler.triggers.date import DateTrigger
import json

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = os.getenv('BOT_TOKEN')
WEB_APP_URL = "https://dar-of-the-flame.github.io/tg-task-frontend/"
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ========== CORS MIDDLEWARE ==========
@middleware
async def cors_middleware(request, handler):
    if request.method == hdrs.METH_OPTIONS:
        response = web.Response()
    else:
        response = await handler(request)
    
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
    user_id = message.from_user.id
    logger.info(f"👤 Пользователь {user_id} запустил бота")
    
    web_app = WebAppInfo(url=f"{WEB_APP_URL}?startapp={user_id}")
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Открыть планировщик", web_app=web_app)]],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
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
    try:
        data = message.web_app_data.data
        user_id = message.from_user.id
        logger.info(f"📱 Данные от user_id={user_id}: {data}")
        
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
    return web.json_response({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})

# Функция для преобразования объектов даты/времени в строки
def convert_db_objects(obj):
    """Рекурсивно преобразует объекты БД в строки для JSON"""
    if isinstance(obj, dict):
        return {k: convert_db_objects(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_db_objects(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif hasattr(obj, 'isoformat'):  # Для time/date объектов
        return obj.isoformat()
    elif hasattr(obj, 'strftime'):  # Для других объектов с strftime
        try:
            return obj.strftime('%H:%M') if hasattr(obj, 'hour') else obj.strftime('%Y-%m-%d')
        except:
            return str(obj)
    else:
        return obj

# Эндпоинт для получения задач
async def get_tasks(request):
    try:
        user_id = request.query.get('user_id')
        if not user_id:
            return web.json_response({"status": "error", "message": "user_id required"}, status=400)
        
        tasks = database.get_tasks_by_user(int(user_id))
        
        # Преобразуем все задачи в формат, подходящий для JSON
        tasks_list = []
        for task in tasks:
            task_dict = dict(task)
            task_dict = convert_db_objects(task_dict)
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
        
        # Для заметки не требуем дату и время
        if data.get('task_type') == 'note':
            data['date'] = None
            data['time'] = None
            data['is_reminder'] = False
        
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
            logger.info(f"✅ Задача {task_id} создана для user_id={user_id}, тип: {data.get('task_type')}")
            
            # Если это напоминание или задача с временем - планируем отправку
            if data.get('is_reminder') and data.get('date') and data.get('time'):
                await schedule_notification(task_id, user_id, data['text'], data['date'], data['time'], 'reminder')
            elif data.get('task_type') == 'task' and data.get('date') and data.get('time'):
                await schedule_notification(task_id, user_id, data['text'], data['date'], data['time'], 'task')
            
            return web.json_response({"status": "ok", "task_id": task_id})
        else:
            logger.error(f"❌ Ошибка создания задачи для user_id={user_id}")
            return web.json_response({"status": "error", "message": "Failed to create task"}, status=500)
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания задачи: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# ========== ФУНКЦИЯ ПЛАНИРОВАНИЯ УВЕДОМЛЕНИЙ ==========
async def schedule_notification(task_id, user_id, text, date_str, time_str, task_type):
    """Планирует отправку уведомления на указанное время (в часовом поясе Москвы)"""
    try:
        # Создаем datetime объект из даты и времени (пользователь вводит в MSK)
        notification_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        
        # Преобразуем в UTC (Render.com работает в UTC, а время у нас в MSK)
        # MSK = UTC+3, поэтому вычитаем 3 часа
        notification_datetime_utc = notification_datetime - timedelta(hours=3)
        
        # Проверяем, что уведомление в будущем
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if notification_datetime_utc <= now_utc:
            logger.warning(f"⚠️ Уведомление {task_id} в прошлом, отправляем сразу")
            await send_notification(task_id, user_id, text, task_type)
            return False
        
        # Добавляем задачу в планировщик (время в UTC)
        scheduler.add_job(
            send_notification,
            trigger=DateTrigger(run_date=notification_datetime_utc),
            args=[task_id, user_id, text, task_type],
            id=f"notification_{task_id}",
            replace_existing=True
        )
        
        moscow_time_str = notification_datetime.strftime("%d.%m.%Y %H:%M")
        logger.info(f"⏰ Уведомление {task_id} запланировано на {moscow_time_str} MSK (UTC+3)")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка планирования уведомления {task_id}: {e}")
        return False

# ========== ФУНКЦИЯ ОТПРАВКИ УВЕДОМЛЕНИЯ ==========
async def send_notification(task_id, user_id, text, task_type):
    """Отправляет уведомление пользователю в зависимости от типа задачи"""
    try:
        logger.info(f"🔔 Отправка {task_type} {task_id} пользователю {user_id}")
        
        if task_type == 'reminder':
            # Напоминание - отправляем и сразу архивируем
            await bot.send_message(
                chat_id=user_id,
                text=f"🔔 *Напоминание!*\n\n{text}\n\n_Время выполнения наступило_",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Помечаем напоминание как отправленное и архивируем
            database.update_task_status(task_id, 'archived')
            logger.info(f"✅ Напоминание {task_id} отправлено и заархивировано")
            
        elif task_type == 'task':
            # Задача - отправляем с кнопками
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Выполнено", callback_data=f"task_done_{task_id}"),
                    InlineKeyboardButton(text="📝 В процессе", callback_data=f"task_progress_{task_id}")
                ]
            ])
            
            await bot.send_message(
                chat_id=user_id,
                text=f"📋 *Задача!*\n\n{text}\n\n_Выберите действие:_",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            logger.info(f"✅ Задача {task_id} отправлена с кнопками")
        
        # Удаляем задачу из планировщика
        try:
            scheduler.remove_job(f"notification_{task_id}")
        except:
            pass
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления {task_id}: {e}")
        # Пробуем отправить позже (через 5 минут)
        try:
            retry_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
            scheduler.add_job(
                send_notification,
                trigger=DateTrigger(run_date=retry_time),
                args=[task_id, user_id, text, task_type],
                id=f"notification_retry_{task_id}_{datetime.now().timestamp()}",
                replace_existing=True
            )
            logger.info(f"🔄 Уведомление {task_id} запланировано на повторную отправку")
        except Exception as retry_error:
            logger.error(f"❌ Ошибка планирования повторной отправки {task_id}: {retry_error}")

# ========== ОБРАБОТКА КНОПОК ЗАДАЧ ==========
@router.callback_query(F.data.startswith("task_"))
async def handle_task_action(callback: CallbackQuery):
    try:
        data = callback.data
        task_id = int(data.split("_")[-1])
        action = data.split("_")[1]
        
        if action == "done":
            # Помечаем задачу как выполненную
            database.update_task_status(task_id, 'completed')
            
            await callback.answer("✅ Задача отмечена как выполненная")
            await callback.message.edit_text(
                f"✅ *Выполнено*\n\n{callback.message.text.split('Задача!')[1].split('_Выберите действие:_')[0]}"
            )
            
        elif action == "progress":
            # Помечаем задачу как в процессе
            database.update_task_status(task_id, 'in_progress')
            
            await callback.answer("📝 Задача отмечена как в процессе")
            await callback.message.edit_text(
                f"📝 *В процессе*\n\n{callback.message.text.split('Задача!')[1].split('_Выберите действие:_')[0]}"
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки действия задачи: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

# ========== ПРОВЕРКА И ОТПРАВКА ОТЛОЖЕННЫХ УВЕДОМЛЕНИЙ ==========
async def check_and_send_pending_notifications():
    """Проверяет и отправляет просроченные уведомления"""
    try:
        notifications = database.get_pending_notifications()
        
        for notification in notifications:
            try:
                task_id = notification['id']
                user_id = notification['user_id']
                text = notification['text']
                task_type = notification['task_type']
                
                # Отправляем уведомление
                await send_notification(task_id, user_id, text, task_type)
                
                # Небольшая задержка между отправками
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"❌ Ошибка обработки уведомления {notification.get('id')}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в check_and_send_pending_notifications: {e}")

# ========== ЗАПУСК ПРИЛОЖЕНИЯ ==========
async def on_startup():
    logger.info("=== Запуск бота ===")
    
    # Инициализируем БД
    database.init_db()
    logger.info("✅ База данных инициализирована")

    # Запускаем планировщик
    scheduler.start()
    logger.info("✅ Планировщик запущен (часовой пояс: Europe/Moscow)")

    # Проверяем и отправляем отложенные уведомления
    await check_and_send_pending_notifications()
    logger.info("✅ Проверка отложенных уведомлений выполнена")

    # Запускаем периодические задачи
    scheduler.add_job(
        check_and_send_pending_notifications,
        'interval',
        minutes=5,
        id='check_pending_notifications',
        replace_existing=True
    )

    scheduler.add_job(
        lambda: database.archive_overdue_tasks(),
        'interval',
        hours=1,
        id='archive_tasks',
        replace_existing=True
    )

    scheduler.add_job(
        lambda: database.cleanup_old_reminders(),
        'interval',
        days=1,
        id='cleanup_reminders',
        replace_existing=True
    )

    # Регистрируем HTTP маршруты
    app.router.add_get('/health', health_check)
    app.router.add_get('/api/tasks', get_tasks)
    app.router.add_post('/api/new_task', create_task)
    app.router.add_post('/api/update_task', lambda r: web.json_response({"status": "ok"}))
    
    # Корневой маршрут
    async def api_info(request):
        return web.json_response({
            "app": "TaskFlow Bot API",
            "status": "running",
            "version": "1.0",
            "timezone": "Europe/Moscow (UTC+3)",
            "endpoints": {
                "GET /health": "Health check",
                "GET /api/tasks?user_id=ID": "Get user tasks",
                "POST /api/new_task": "Create new task",
                "POST /api/update_task": "Update task"
            }
        })
    
    app.router.add_get('/', api_info)
    app.router.add_get('/api', api_info)

    # Настраиваем webhook
    if WEBHOOK_HOST:
        try:
            webhook_info = await bot.get_webhook_info()
            
            if webhook_info.url != WEBHOOK_URL:
                await bot.set_webhook(WEBHOOK_URL, secret_token=API_TOKEN)
                logger.info(f"🌐 Webhook установлен: {WEBHOOK_URL}")
            else:
                logger.info(f"✅ Webhook уже установлен")
                
        except Exception as e:
            logger.error(f"❌ Ошибка настройки webhook: {e}")
        
        webhook_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=API_TOKEN
        )
        
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
                "⏰ Часовой пояс: Europe/Moscow (UTC+3)\n\n"
                "🚀 Бот готов к работе!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить администратора: {e}")

    logger.info("✅ Бот полностью инициализирован и готов к работе")

async def on_shutdown():
    logger.info("=== Остановка бота ===")
    
    if WEBHOOK_HOST:
        try:
            await bot.delete_webhook()
            logger.info("🌐 Webhook удален")
        except Exception as e:
            logger.error(f"❌ Ошибка удаления webhook: {e}")
    
    scheduler.shutdown()
    logger.info("✅ Планировщик остановлен")

async def main():
    await on_startup()

    setup_application(app, dp, bot=bot)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 8080))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот @{bot_info.username} запущен")
    logger.info(f"📱 WebApp URL: {WEB_APP_URL}")
    logger.info(f"🌐 API доступно по: https://{WEBHOOK_HOST}" if WEBHOOK_HOST else "🌐 API доступно локально")

    if WEBHOOK_HOST:
        logger.info("📡 Работаем в режиме webhook")
        await asyncio.Event().wait()
    else:
        logger.warning("⚠️ Работаем без webhook (режим long-polling)")
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
