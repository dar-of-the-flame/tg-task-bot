import os
import logging
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    """Создаёт синхронное подключение к БД."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Создаёт таблицу tasks при первом запуске с ПОЛНОЙ структурой."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Удаляем старую таблицу (осторожно - данные потеряются!)
        cur.execute('DROP TABLE IF EXISTS tasks')
        
        # Создаём новую таблицу с полной структурой
        cur.execute('''
            CREATE TABLE tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                text TEXT NOT NULL,
                category TEXT DEFAULT 'personal',
                priority TEXT DEFAULT 'medium',
                date DATE,
                time TIME,
                reminder INTEGER DEFAULT 0,
                completed BOOLEAN DEFAULT FALSE,
                deleted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP,
                deleted_at TIMESTAMP,
                emoji TEXT DEFAULT '📝',
                remind_at TIMESTAMP,
                reminder_sent BOOLEAN DEFAULT FALSE,
                is_reminder BOOLEAN DEFAULT FALSE,
                archived BOOLEAN DEFAULT FALSE
            )
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Таблица 'tasks' создана с полной структурой")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def add_task(user_id, text, date=None, time=None, reminder=0, 
             category='personal', priority='medium', emoji='📝',
             is_reminder=False):
    """Добавляет задачу в БД. Возвращает ID созданной задачи или None."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Рассчитываем remind_at - только для напоминаний
        remind_at = None
        if date and time and is_reminder:
            try:
                # Создаём полную дату-время
                if isinstance(date, str):
                    task_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                else:
                    # Если date уже datetime
                    task_datetime = datetime.combine(date, datetime.strptime(time, "%H:%M").time())
                
                # Для обычных задач не устанавливаем напоминание
                # Для напоминаний - точное время
                remind_at = task_datetime
            except Exception as e:
                logger.error(f"Ошибка преобразования даты/времени: {e}")
                remind_at = None
        
        cur.execute('''
            INSERT INTO tasks (user_id, text, category, priority, 
                              date, time, reminder, emoji, remind_at, is_reminder)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (user_id, text, category, priority, date, time, reminder, emoji, remind_at, is_reminder))
        
        task_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}, тип: {'напоминание' if is_reminder else 'задача'}")
        return task_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления задачи: {e}")
        return None

def get_tasks_by_user(user_id, include_archived=False):
    """Возвращает все задачи пользователя."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        if include_archived:
            cur.execute('''
                SELECT id, user_id, text, category, priority, date, time,
                       reminder, completed, deleted, created_at, completed_at,
                       deleted_at, emoji, is_reminder, archived
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                ORDER BY date, time
            ''', (user_id,))
        else:
            cur.execute('''
                SELECT id, user_id, text, category, priority, date, time,
                       reminder, completed, deleted, created_at, completed_at,
                       deleted_at, emoji, is_reminder, archived
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                AND archived = FALSE
                ORDER BY date, time
            ''', (user_id,))
        
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения задач: {e}")
        return []

def update_task(task_id, user_id, completed=None, deleted=None, archived=None):
    """Обновляет задачу (отметка выполнения или удаление)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        if completed is not None:
            if completed:
                cur.execute('''
                    UPDATE tasks 
                    SET completed = TRUE, completed_at = NOW() 
                    WHERE id = %s AND user_id = %s
                ''', (task_id, user_id))
            else:
                cur.execute('''
                    UPDATE tasks 
                    SET completed = FALSE, completed_at = NULL 
                    WHERE id = %s AND user_id = %s
                ''', (task_id, user_id))
        
        if deleted:
            cur.execute('''
                UPDATE tasks 
                SET deleted = TRUE, deleted_at = NOW() 
                WHERE id = %s AND user_id = %s
            ''', (task_id, user_id))
        
        if archived is not None:
            cur.execute('''
                UPDATE tasks 
                SET archived = %s 
                WHERE id = %s AND user_id = %s
            ''', (archived, task_id, user_id))
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Задача {task_id} обновлена")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи: {e}")
        return False

def get_pending_reminders():
    """Возвращает список напоминаний, для которых пора отправить уведомление."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, user_id, text
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND is_reminder = TRUE
            AND remind_at <= NOW()
            AND deleted = FALSE
            AND completed = FALSE
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

def archive_overdue_tasks():
    """Перемещает просроченные задачи в архив."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Находим просроченные задачи (дата в прошлом, не выполнены, не удалены)
        cur.execute('''
            UPDATE tasks 
            SET archived = TRUE
            WHERE date < CURRENT_DATE
            AND completed = FALSE
            AND deleted = FALSE
            AND archived = FALSE
            AND is_reminder = FALSE
        ''')
        
        affected_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✅ Архивировано {affected_rows} просроченных задач")
        return affected_rows
    except Exception as e:
        logger.error(f"❌ Ошибка архивации просроченных задач: {e}")
        return 0
