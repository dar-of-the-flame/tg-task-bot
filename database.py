import os
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    """Создаёт синхронное подключение к БД."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Создаёт таблицу tasks при первом запуске."""
    try:
        conn = get_connection()
        cur = conn.cursor()
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
        cur.close()
        conn.close()
        logger.info("✅ Таблица 'tasks' готова")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def add_task(user_id, emoji, task_text, remind_at, start_time=None, end_time=None):
    """Добавляет задачу в БД. Возвращает ID созданной задачи или None."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO tasks (user_id, emoji, task_text, remind_at, start_time, end_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (user_id, emoji, task_text, remind_at, start_time, end_time))
        task_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}")
        return task_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления задачи: {e}")
        return None

def get_pending_reminders():
    """Возвращает список задач, для которых пора отправить напоминание."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, user_id, emoji, task_text, start_time
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND remind_at <= NOW() + INTERVAL '1 minute'
            AND remind_at > NOW() - INTERVAL '5 minutes'
        ''')
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения напоминаний: {e}")
        return []

def mark_reminder_sent(task_id):
    """Помечает напоминание как отправленное."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('UPDATE tasks SET reminder_sent = TRUE WHERE id = %s', (task_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")
