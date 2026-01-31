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
        
        # Создаем таблицу с полной структурой
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                emoji TEXT DEFAULT '📌',
                task_text TEXT NOT NULL,
                category TEXT DEFAULT 'personal',
                priority TEXT DEFAULT 'medium',
                date DATE,
                time TIME,
                remind_at TIMESTAMP NOT NULL,
                reminder_sent BOOLEAN DEFAULT FALSE,
                completed BOOLEAN DEFAULT FALSE,
                deleted BOOLEAN DEFAULT FALSE,
                completed_at TIMESTAMP,
                deleted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                start_time TIMESTAMP,
                end_time TIMESTAMP
            )
        ''')
        
        # Создаем индексы для быстрого поиска
        cur.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON tasks(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_remind_at ON tasks(remind_at)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_completed ON tasks(completed)')
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Таблица 'tasks' создана с полной структурой")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def add_task(user_id, emoji, task_text, remind_at, **kwargs):
    """Добавляет задачу в БД с полной структурой."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Подготавливаем параметры
        category = kwargs.get('category', 'personal')
        priority = kwargs.get('priority', 'medium')
        date = kwargs.get('date')
        time = kwargs.get('time', '')
        completed = kwargs.get('completed', False)
        start_time = kwargs.get('start_time')
        end_time = kwargs.get('end_time')
        
        cur.execute('''
            INSERT INTO tasks 
            (user_id, emoji, task_text, category, priority, date, time, 
             remind_at, completed, start_time, end_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (user_id, emoji, task_text, category, priority, date, time, 
              remind_at, completed, start_time, end_time))
        
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
    """Возвращает все задачи пользователя (кроме удалённых)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT id, emoji, task_text, category, priority, date, time,
                   remind_at, completed, deleted, created_at
            FROM tasks 
            WHERE user_id = %s AND deleted = FALSE
            ORDER BY date DESC, created_at DESC
        ''', (user_id,))
        
        tasks = cur.fetchall()
        
        # Преобразуем типы для JSON
        for task in tasks:
            if task['date']:
                task['date'] = task['date'].isoformat()
            if task['time']:
                task['time'] = str(task['time'])
            if task['remind_at']:
                task['remind_at'] = task['remind_at'].isoformat()
            if task['created_at']:
                task['created_at'] = task['created_at'].isoformat()
        
        cur.close()
        conn.close()
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения задач пользователя: {e}")
        return []

def get_pending_reminders():
    """Возвращает список задач, для которых пора отправить напоминание."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT id, user_id, emoji, task_text
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND deleted = FALSE
            AND completed = FALSE
            AND remind_at <= NOW()
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
        
        cur.execute('''
            UPDATE tasks 
            SET reminder_sent = TRUE 
            WHERE id = %s
        ''', (task_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✅ Напоминание {task_id} отмечено как отправленное")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")

def update_task(task_id, **kwargs):
    """Обновляет задачу (например, помечает как выполненную)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        update_fields = []
        update_values = []
        
        if 'completed' in kwargs:
            update_fields.append("completed = %s")
            update_values.append(kwargs['completed'])
            
            if kwargs['completed']:
                update_fields.append("completed_at = NOW()")
            else:
                update_fields.append("completed_at = NULL")
        
        if 'deleted' in kwargs:
            update_fields.append("deleted = %s")
            update_values.append(kwargs['deleted'])
            
            if kwargs['deleted']:
                update_fields.append("deleted_at = NOW()")
            else:
                update_fields.append("deleted_at = NULL")
        
        if not update_fields:
            return False
        
        update_values.append(task_id)
        
        query = f'''
            UPDATE tasks 
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id
        '''
        
        cur.execute(query, update_values)
        result = cur.fetchone()
        
        conn.commit()
        cur.close()
        conn.close()
        
        if result:
            logger.info(f"✅ Задача {task_id} обновлена")
            return True
        return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")
        return False
