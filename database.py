import asyncpg
import os
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

async def get_db_connection():
    """Создаёт и возвращает подключение к базе."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        raise

async def init_db():
    """Создаёт таблицу, если её нет."""
    try:
        conn = await get_db_connection()
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                emoji TEXT,
                task_text TEXT NOT NULL,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                remind_at TIMESTAMP NOT NULL,
                reminder_sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        await conn.close()
        logger.info("Таблица 'tasks' создана или уже существует.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")

async def add_task(user_id, emoji, task_text, remind_at, start_time=None, end_time=None):
    """Добавляет новую задачу в базу."""
    try:
        conn = await get_db_connection()
        await conn.execute('''
            INSERT INTO tasks (user_id, emoji, task_text, remind_at, start_time, end_time)
            VALUES ($1, $2, $3, $4, $5, $6)
        ''', user_id, emoji, task_text, remind_at, start_time, end_time)
        await conn.close()
        logger.info(f"Задача добавлена для user_id={user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении задачи: {e}")
        return False

async def get_pending_reminders():
    """Возвращает список задач, для которых пора отправить напоминание."""
    try:
        conn = await get_db_connection()
        rows = await conn.fetch('''
            SELECT id, user_id, emoji, task_text, start_time
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND remind_at <= NOW() + INTERVAL '1 minute'
            AND remind_at > NOW() - INTERVAL '5 minutes'
        ''')
        await conn.close()
        return rows
    except Exception as e:
        logger.error(f"Ошибка при получении напоминаний: {e}")
        return []

async def mark_reminder_sent(task_id):
    """Помечает напоминание как отправленное."""
    try:
        conn = await get_db_connection()
        await conn.execute('UPDATE tasks SET reminder_sent = TRUE WHERE id = $1', task_id)
        await conn.close()
    except Exception as e:
        logger.error(f"Ошибка при обновлении задачи {task_id}: {e}")
