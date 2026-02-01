import os
import logging
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_connection():
    """Создает соединение с базой данных"""
    try:
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            return psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        else:
            return psycopg2.connect(
                dbname=os.getenv('DB_NAME', 'taskflow'),
                user=os.getenv('DB_USER', 'postgres'),
                password=os.getenv('DB_PASSWORD', ''),
                host=os.getenv('DB_HOST', 'localhost'),
                cursor_factory=RealDictCursor
            )
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        raise

def init_db():
    """Инициализация таблиц в базе данных"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Создаем таблицу задач
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                text TEXT NOT NULL,
                category TEXT DEFAULT 'personal',
                priority TEXT DEFAULT 'medium',
                date DATE,
                time TIME,
                reminder INTEGER DEFAULT 0,
                emoji TEXT DEFAULT '📝',
                completed BOOLEAN DEFAULT FALSE,
                deleted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                deleted_at TIMESTAMP,
                remind_at TIMESTAMP,
                reminder_sent BOOLEAN DEFAULT FALSE,
                is_reminder BOOLEAN DEFAULT FALSE,
                archived BOOLEAN DEFAULT FALSE,
                task_type TEXT DEFAULT 'task'
            )
        ''')

        cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_remind_at ON tasks(remind_at)')
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        raise

def add_task(user_id, text, date=None, time=None, reminder=0, 
             category='personal', priority='medium', emoji='📝',
             is_reminder=False, task_type='task'):
    """Добавляет задачу в БД"""
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Рассчитываем remind_at для напоминаний
        remind_at = None
        if is_reminder and date and time:
            try:
                # Время приходит в MSK (UTC+3), но база работает в UTC
                # Конвертируем в UTC
                task_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                # Вычитаем 3 часа для UTC
                task_datetime_utc = task_datetime - timedelta(hours=3)
                remind_at = task_datetime_utc
                logger.info(f"📅 Напоминание установлено на: {date} {time} MSK (UTC+3)")
            except Exception as e:
                logger.error(f"❌ Ошибка преобразования времени: {e}")
                remind_at = None

        cur.execute('''
            INSERT INTO tasks (user_id, text, category, priority, 
                              date, time, reminder, emoji, remind_at, 
                              is_reminder, task_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (user_id, text, category, priority, date, time, 
              reminder, emoji, remind_at, is_reminder, task_type))

        task_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}, тип: {task_type}, напоминание: {is_reminder}")
        return task_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления задачи: {e}")
        return None

def get_tasks_by_user(user_id, include_archived=False):
    """Получает задачи пользователя"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        if include_archived:
            cur.execute('''
                SELECT id, user_id, text, category, priority, date, time,
                      reminder, completed, deleted, created_at, completed_at,
                      deleted_at, emoji, is_reminder, archived, task_type
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                ORDER BY 
                    CASE WHEN date IS NULL THEN 1 ELSE 0 END,
                    date,
                    CASE WHEN time IS NULL THEN 1 ELSE 0 END,
                    time
            ''', (user_id,))
        else:
            cur.execute('''
                SELECT id, user_id, text, category, priority, date, time,
                      reminder, completed, deleted, created_at, completed_at,
                      deleted_at, emoji, is_reminder, archived, task_type
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                AND archived = FALSE
                ORDER BY 
                    CASE WHEN date IS NULL THEN 1 ELSE 0 END,
                    date,
                    CASE WHEN time IS NULL THEN 1 ELSE 0 END,
                    time
            ''', (user_id,))

        tasks = cur.fetchall()
        cur.close()
        conn.close()
        
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения задач: {e}")
        return []

def update_task(task_id, user_id, updates):
    """Обновляет задачу"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        set_clause = []
        params = []
        
        for key, value in updates.items():
            set_clause.append(f"{key} = %s")
            params.append(value)
        
        params.extend([task_id, user_id])
        
        query = f'''
            UPDATE tasks 
            SET {', '.join(set_clause)}
            WHERE id = %s AND user_id = %s
            RETURNING id
        '''
        
        cur.execute(query, params)
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи: {e}")
        return False

def get_pending_reminders():
    """Получает задачи, для которых нужно отправить напоминания"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Ищем напоминания, у которых remind_at наступил (в UTC)
        cur.execute('''
            SELECT id, user_id, text, date, time, emoji, remind_at
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND is_reminder = TRUE
            AND remind_at <= NOW() AT TIME ZONE 'UTC'
            AND deleted = FALSE
            AND completed = FALSE
            AND archived = FALSE
            ORDER BY remind_at
        ''')
        
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        
        logger.info(f"🔔 Найдено напоминаний для отправки: {len(tasks)}")
        for task in tasks:
            logger.info(f"   - Задача {task['id']}: {task['text'][:50]}...")
        
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения напоминаний: {e}")
        return []

def mark_reminder_sent(task_id):
    """Отмечает напоминание как отправленное и архивирует его"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE tasks 
            SET reminder_sent = TRUE,
                archived = TRUE
            WHERE id = %s
        ''', (task_id,))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Напоминание {task_id} помечено как отправленное и заархивировано")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")

def archive_overdue_tasks():
    """Архивирует просроченные задачи"""
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute('''
            UPDATE tasks 
            SET archived = TRUE
            WHERE date < CURRENT_DATE 
            AND completed = FALSE 
            AND deleted = FALSE 
            AND is_reminder = FALSE
            AND archived = FALSE
            RETURNING id
        ''')
        
        archived_tasks = cur.fetchall()
        archived_count = len(archived_tasks)
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"📦 Заархивировано {archived_count} просроченных задач")
        return archived_count
    except Exception as e:
        logger.error(f"❌ Ошибка архивации просроченных задач: {e}")
        return 0

def cleanup_old_reminders():
    """Очищает старые отправленные напоминания (старше 7 дней)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute('''
            DELETE FROM tasks 
            WHERE is_reminder = TRUE
            AND reminder_sent = TRUE
            AND remind_at < NOW() - INTERVAL '7 days'
        ''')
        
        affected_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"🧹 Удалено {affected_rows} старых напоминаний")
        return affected_rows
    except Exception as e:
        logger.error(f"❌ Ошибка очистки старых напоминаний: {e}")
        return 0
