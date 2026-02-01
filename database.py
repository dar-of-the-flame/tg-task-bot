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
                task_type TEXT DEFAULT 'task',
                status TEXT DEFAULT 'active'
            )
        ''')

        # Создаем индексы (используем IF NOT EXISTS для PostgreSQL)
        try:
            cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_remind_at ON tasks(remind_at)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
        except Exception as e:
            logger.warning(f"⚠️ Ошибка создания индекса, возможно уже существует: {e}")
            # Если индексы уже существуют, продолжаем
        
        # Проверяем и добавляем недостающие колонки
        try:
            # Проверяем наличие колонки status
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='tasks' AND column_name='status'
            """)
            if not cur.fetchone():
                cur.execute('ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT \'active\'')
                logger.info("✅ Добавлена колонка status")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки/добавления колонки status: {e}")
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ База данных инициализирована")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        # Не падаем полностью, возможно таблица уже создана
        try:
            conn.close()
        except:
            pass

def add_task(user_id, text, date=None, time=None, reminder=0, 
             category='personal', priority='medium', emoji='📝',
             is_reminder=False, task_type='task'):
    """Добавляет задачу в БД"""
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Рассчитываем remind_at для уведомлений
        remind_at = None
        if (is_reminder or task_type == 'task') and date and time:
            try:
                # Время приходит в MSK (UTC+3)
                task_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                # Вычитаем 3 часа для UTC
                task_datetime_utc = task_datetime - timedelta(hours=3)
                remind_at = task_datetime_utc
                logger.info(f"📅 Уведомление установлено на: {date} {time} MSK (UTC+3)")
            except Exception as e:
                logger.error(f"❌ Ошибка преобразования времени: {e}")
                remind_at = None

        cur.execute('''
            INSERT INTO tasks (user_id, text, category, priority, 
                              date, time, reminder, emoji, remind_at, 
                              is_reminder, task_type, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
            RETURNING id
        ''', (user_id, text, category, priority, date, time, 
              reminder, emoji, remind_at, is_reminder, task_type))

        task_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}, тип: {task_type}")
        return task_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления задачи: {e}")
        try:
            conn.close()
        except:
            pass
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
                      deleted_at, emoji, is_reminder, archived, task_type, status
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
                      deleted_at, emoji, is_reminder, archived, task_type, status
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                AND archived = FALSE
                AND (status IS NULL OR status != 'archived')
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
        try:
            conn.close()
        except:
            pass
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
        try:
            conn.close()
        except:
            pass
        return False

def update_task_status(task_id, status):
    """Обновляет статус задачи"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        if status == 'completed':
            cur.execute('''
                UPDATE tasks 
                SET completed = TRUE,
                    completed_at = CURRENT_TIMESTAMP,
                    archived = TRUE,
                    status = 'completed'
                WHERE id = %s
                RETURNING id
            ''', (task_id,))
        elif status == 'in_progress':
            cur.execute('''
                UPDATE tasks 
                SET completed = FALSE,
                    archived = FALSE,
                    status = 'in_progress'
                WHERE id = %s
                RETURNING id
            ''', (task_id,))
        elif status == 'archived':
            cur.execute('''
                UPDATE tasks 
                SET archived = TRUE,
                    status = 'archived'
                WHERE id = %s
                RETURNING id
            ''', (task_id,))
        
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✅ Статус задачи {task_id} обновлен на {status}")
        return result is not None
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса задачи: {e}")
        try:
            conn.close()
        except:
            pass
        return False

def get_pending_notifications():
    """Получает задачи, для которых нужно отправить уведомления"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Ищем уведомления, у которых remind_at наступил (в UTC)
        cur.execute('''
            SELECT id, user_id, text, date, time, emoji, remind_at, task_type, is_reminder
            FROM tasks 
            WHERE remind_at IS NOT NULL
            AND remind_at <= NOW() AT TIME ZONE 'UTC'
            AND deleted = FALSE
            AND completed = FALSE
            AND archived = FALSE
            AND (status IS NULL OR status = 'active')
            AND (is_reminder = TRUE OR task_type = 'task')
            ORDER BY remind_at
        ''')
        
        tasks = cur.fetchall()
        cur.close()
        conn.close()
        
        logger.info(f"🔔 Найдено уведомлений для отправки: {len(tasks)}")
        return tasks
    except Exception as e:
        logger.error(f"❌ Ошибка получения уведомлений: {e}")
        try:
            conn.close()
        except:
            pass
        return []

def archive_overdue_tasks():
    """Архивирует просроченные задачи"""
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute('''
            UPDATE tasks 
            SET archived = TRUE,
                status = 'archived'
            WHERE date < CURRENT_DATE 
            AND completed = FALSE 
            AND deleted = FALSE 
            AND is_reminder = FALSE
            AND archived = FALSE
            AND (status IS NULL OR status = 'active')
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
        try:
            conn.close()
        except:
            pass
        return 0

def cleanup_old_reminders():
    """Очищает старые отправленные напоминания (старше 7 дней)."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute('''
            DELETE FROM tasks 
            WHERE is_reminder = TRUE
            AND archived = TRUE
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
        try:
            conn.close()
        except:
            pass
        return 0
