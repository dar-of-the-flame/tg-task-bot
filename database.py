import os
import logging
from datetime import datetime, timedelta
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor

@@ -42,7 +42,8 @@ def init_db():
                remind_at TIMESTAMP,
                reminder_sent BOOLEAN DEFAULT FALSE,
                is_reminder BOOLEAN DEFAULT FALSE,
                archived BOOLEAN DEFAULT FALSE
                archived BOOLEAN DEFAULT FALSE,
                task_type TEXT DEFAULT 'task'
            )
        ''')

@@ -57,43 +58,40 @@ def init_db():

def add_task(user_id, text, date=None, time=None, reminder=0, 
             category='personal', priority='medium', emoji='📝',
             is_reminder=False):
             is_reminder=False, task_type='task'):
    """Добавляет задачу в БД. Возвращает ID созданной задачи или None."""
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Рассчитываем remind_at - только для напоминаний
        # Рассчитываем remind_at для напоминаний
        remind_at = None
        if date and time and is_reminder:
        if is_reminder and date and time:
            try:
                # Создаём полную дату-время
                if isinstance(date, str):
                    task_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                else:
                    # Если date уже datetime
                    task_datetime = datetime.combine(date, datetime.strptime(time, "%H:%M").time())
                
                # Для обычных задач не устанавливаем напоминание
                # Для напоминаний - точное время
                # Создаём дату-время из даты и времени
                task_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                # Устанавливаем remind_at как точное время напоминания
                remind_at = task_datetime
                logger.info(f"📅 Напоминание установлено на: {remind_at}")
            except Exception as e:
                logger.error(f"Ошибка преобразования даты/времени: {e}")
                logger.error(f"❌ Ошибка преобразования времени: {e}")
                remind_at = None

        cur.execute('''
            INSERT INTO tasks (user_id, text, category, priority, 
                              date, time, reminder, emoji, remind_at, is_reminder)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                              date, time, reminder, emoji, remind_at, 
                              is_reminder, task_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (user_id, text, category, priority, date, time, reminder, emoji, remind_at, is_reminder))
        ''', (user_id, text, category, priority, date, time, 
              reminder, emoji, remind_at, is_reminder, task_type))

        task_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}, тип: {'напоминание' if is_reminder else 'задача'}")
        logger.info(f"✅ Задача {task_id} добавлена для user_id={user_id}, тип: {task_type}, напоминание: {is_reminder}")
        return task_id
    except Exception as e:
        logger.error(f"❌ Ошибка добавления задачи: {e}")
@@ -109,22 +107,30 @@ def get_tasks_by_user(user_id, include_archived=False):
            cur.execute('''
                SELECT id, user_id, text, category, priority, date, time,
                       reminder, completed, deleted, created_at, completed_at,
                       deleted_at, emoji, is_reminder, archived
                       deleted_at, emoji, is_reminder, archived, task_type
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                ORDER BY date, time
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
                       deleted_at, emoji, is_reminder, archived
                       deleted_at, emoji, is_reminder, archived, task_type
                FROM tasks 
                WHERE user_id = %s 
                AND deleted = FALSE
                AND archived = FALSE
                ORDER BY date, time
                ORDER BY 
                    CASE WHEN date IS NULL THEN 1 ELSE 0 END,
                    date,
                    CASE WHEN time IS NULL THEN 1 ELSE 0 END,
                    time
            ''', (user_id,))

        tasks = cur.fetchall()
@@ -183,18 +189,28 @@ def get_pending_reminders():
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Ищем напоминания, время которых наступило ИЛИ уже прошло, но не отправлены
        cur.execute('''
            SELECT id, user_id, text
            SELECT id, user_id, text, date, time, emoji
            FROM tasks 
            WHERE reminder_sent = FALSE 
            AND is_reminder = TRUE
            AND remind_at <= NOW()
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
@@ -205,10 +221,15 @@ def mark_reminder_sent(task_id):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('UPDATE tasks SET reminder_sent = TRUE WHERE id = %s', (task_id,))
        cur.execute('''
            UPDATE tasks 
            SET reminder_sent = TRUE 
            WHERE id = %s
        ''', (task_id,))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Напоминание {task_id} помечено как отправленное")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления задачи {task_id}: {e}")

@@ -218,7 +239,7 @@ def archive_overdue_tasks():
        conn = get_connection()
        cur = conn.cursor()

        # Находим просроченные задачи (дата в прошлом, не выполнены, не удалены)
        # Находим просроченные задачи (дата в прошлом, не выполнены, не удалены, не напоминания)
        cur.execute('''
            UPDATE tasks 
            SET archived = TRUE
@@ -239,3 +260,27 @@ def archive_overdue_tasks():
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
