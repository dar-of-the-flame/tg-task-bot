import os
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
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
                completed BOOLEAN DEFAULT FALSE,
                deleted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP,
                deleted_at TIMESTAMP,
                category TEXT DEFAULT 'personal',
                priority TEXT DEFAULT 'medium'
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

def add_task(user_id, emoji, task_text, remind_at, start_time=None, end_time=None, category='personal', priority='medium'):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO tasks (user_id, emoji, task_text, remind_at, start_time, end_time, category, priority)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (user_id, emoji, task_text, remind_at, start_time, end_time, category, priority))
        task_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}")
        return task_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления задачи: {e}")
        return None

def get_user_tasks(user_id):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, user_id, emoji, task_text as text, 
                   start_time, end_time, remind_at,
                   reminder_sent, completed, deleted,
                   created_at, completed_at, deleted_at,
                   category, priority
            FROM tasks 
            WHERE user_id = %s
            ORDER BY created_at DESC
        ''', (user_id,))
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        
        result = []
        for task in tasks:
            # Форматируем дату и время для фронтенда
            date_str = None
            time_str = ''
            if task['start_time']:
                date_str = task['start_time'].date().isoformat()
                time_str = task['start_time'].strftime('%H:%M')
            
            result.append({
                'id': task['id'],
                'user_id': task['user_id'],
                'emoji': task['emoji'],
                'text': task['text'],
                'category': task['category'] or 'personal',
                'priority': task['priority'] or 'medium',
                'completed': task['completed'] or False,
                'deleted': task['deleted'] or False,
                'created_at': task['created_at'].isoformat() if task['created_at'] else None,
                'completed_at': task['completed_at'].isoformat() if task['completed_at'] else None,
                'deleted_at': task['deleted_at'].isoformat() if task['deleted_at'] else None,
                'date': date_str,
                'time': time_str,
                'reminder': 0  # Можно рассчитать из remind_at
            })
        
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения задач user_id={user_id}: {e}")
        return []

def get_pending_reminders():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, user_id, emoji, task_text, start_time
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND remind_at <= NOW() + INTERVAL '1 minute'
            AND remind_at > NOW() - INTERVAL '5 minutes'
            AND completed = FALSE
            AND deleted = FALSE
        ''')
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения напоминаний: {e}")
        return []

def mark_reminder_sent(task_id):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('UPDATE tasks SET reminder_sent = TRUE WHERE id = %s', (task_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")
