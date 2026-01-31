def init_db():
    """Создаёт таблицу tasks при первом запуске."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Удаляем старую таблицу (данные потеряются, но это лучше чем ничего)
        cur.execute('DROP TABLE IF EXISTS tasks')
        
        # Создаём новую таблицу с ПОЛНОЙ структурой
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
                completed BOOLEAN DEFAULT FALSE,
                deleted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP,
                deleted_at TIMESTAMP,
                emoji TEXT DEFAULT '📝',
                remind_at TIMESTAMP,
                reminder_sent BOOLEAN DEFAULT FALSE
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
