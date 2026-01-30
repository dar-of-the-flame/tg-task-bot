import psycopg2
import psycopg2.extras
import os
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к БД."""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Создаёт таблицу, если её нет."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
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
                conn.commit()
        logger.info("Таблица 'tasks' создана или уже существует.")
        return True
    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")
        return False

def add_task(user_id, emoji, task_text, remind_at, start_time=None, end_time=None):
    """Добавляет новую задачу в базу."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO tasks (user_id, emoji, task_text, remind_at, start_time, end_time)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (user_id, emoji, task_text, remind_at, start_time, end_time))
                conn.commit()
        logger.info(f"Задача добавлена для user_id={user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении задачи: {e}")
        return False

def get_pending_reminders():
    """Возвращает список задач, для которых пора отправить напоминание."""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute('''
                    SELECT id, user_id, emoji, task_text, start_time
                    FROM tasks 
                    WHERE reminder_sent = FALSE 
                    AND remind_at <= NOW() + INTERVAL '1 minute'
                    AND remind_at > NOW() - INTERVAL '5 minutes'
                ''')
                return cur.fetchall()
    except Exception as e:
        logger.error(f"Ошибка при получении напоминаний: {e}")
        return []

def mark_reminder_sent(task_id):
    """Помечает напоминание как отправленное."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE tasks SET reminder_sent = TRUE WHERE id = %s', (task_id,))
                conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении задачи {task_id}: {e}")
