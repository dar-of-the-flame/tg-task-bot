import os
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    """Создаёт подключение к БД"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Инициализация БД с проверкой и добавлением колонок"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Создаём таблицу если не существует
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
        
        # Проверяем существующие колонки
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'tasks'
        """)
        existing_columns = [row['column_name'] for row in cur.fetchall()]
        
        # Список колонок для проверки
        required_columns = [
            ('completed', 'BOOLEAN DEFAULT FALSE'),
            ('deleted', 'BOOLEAN DEFAULT FALSE'),
            ('category', 'TEXT DEFAULT \'personal\''),
            ('priority', 'TEXT DEFAULT \'medium\''),
            ('completed_at', 'TIMESTAMP'),
            ('deleted_at', 'TIMESTAMP')
        ]
        
        # Добавляем недостающие колонки
        for column_name, column_type in required_columns:
            if column_name not in existing_columns:
                cur.execute(f'ALTER TABLE tasks ADD COLUMN {column_name} {column_type}')
                logger.info(f"✅ Добавлена колонка {column_name}")
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Таблица 'tasks' готова")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def add_task(user_id, emoji, task_text, remind_at, start_time=None, end_time=None, category='personal', priority='medium'):
    """Добавление задачи в БД"""
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
    """Получение всех задач пользователя"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT 
                id, user_id, emoji, task_text as text,
                start_time, end_time, remind_at,
                reminder_sent, completed, deleted,
                created_at, completed_at, deleted_at,
                category, priority
            FROM tasks 
            WHERE user_id = %s
            ORDER BY 
                CASE 
                    WHEN start_time IS NOT NULL THEN start_time
                    ELSE created_at 
                END DESC
        ''', (user_id,))
        
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        
        # Форматируем результат для фронтенда
        result = []
        for task in tasks:
            # Дата и время
            date_str = None
            time_str = ''
            if task['start_time']:
                date_str = task['start_time'].date().isoformat()
                time_str = task['start_time'].strftime('%H:%M')
            
            # Время создания
            created_at = task['created_at']
            if isinstance(created_at, datetime):
                created_at = created_at.isoformat()
            
            # Время завершения
            completed_at = task['completed_at']
            if completed_at and isinstance(completed_at, datetime):
                completed_at = completed_at.isoformat()
            
            # Время удаления
            deleted_at = task['deleted_at']
            if deleted_at and isinstance(deleted_at, datetime):
                deleted_at = deleted_at.isoformat()
            
            result.append({
                'id': task['id'],
                'user_id': task['user_id'],
                'emoji': task['emoji'],
                'text': task['text'],
                'category': task['category'] or 'personal',
                'priority': task['priority'] or 'medium',
                'completed': task['completed'] or False,
                'deleted': task['deleted'] or False,
                'created_at': created_at,
                'completed_at': completed_at,
                'deleted_at': deleted_at,
                'date': date_str,
                'time': time_str,
                'reminder': 0
            })
        
        logger.info(f"✅ Получено {len(result)} задач для user_id={user_id}")
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения задач user_id={user_id}: {e}")
        return []

def get_pending_reminders():
    """Получение задач для напоминаний"""
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
    """Пометка напоминания как отправленного"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('UPDATE tasks SET reminder_sent = TRUE WHERE id = %s', (task_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")
