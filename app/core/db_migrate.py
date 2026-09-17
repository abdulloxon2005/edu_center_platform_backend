import logging
import sqlite3
import os
from app.core.database import Base
from app.core.config import settings
import app.models.models  # Ensure all models are registered

logger = logging.getLogger(__name__)

def ensure_sqlite_columns():
    """SQLite faylidagi barcha jadvallar uchun Base metadata dagi barcha ustunlar mavjudligini ta'minlash"""
    try:
        db_url = settings.DATABASE_URL
        if "sqlite" not in db_url:
            return
        
        # e.g. sqlite+aiosqlite:///./oquv_markaz.db or sqlite:///./oquv_markaz.db
        db_path = db_url.split("///")[-1]
        if db_path.startswith("./"):
            db_path = db_path[2:]
        
        if not os.path.exists(db_path):
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = [row[0] for row in cursor.fetchall()]

        for table_name, table in Base.metadata.tables.items():
            if table_name in existing_tables:
                cursor.execute(f"PRAGMA table_info({table_name});")
                existing_cols = {row[1]: row for row in cursor.fetchall()}
                for col in table.columns:
                    if col.name not in existing_cols:
                        type_str = str(col.type).upper()
                        if "INT" in type_str:
                            col_type = "INTEGER"
                        elif "FLOAT" in type_str or "NUMERIC" in type_str or "REAL" in type_str:
                            col_type = "REAL"
                        elif "BOOL" in type_str:
                            col_type = "BOOLEAN"
                        elif "DATE" in type_str or "TIME" in type_str:
                            col_type = "TIMESTAMP"
                        else:
                            col_type = "TEXT"
                        
                        alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type};"
                        logger.info(f"Database auto-migration: {alter_sql}")
                        cursor.execute(alter_sql)
        
        conn.commit()
        conn.close()
        logger.info("SQLite auto-migration completed successfully.")
    except Exception as e:
        logger.error(f"Error during SQLite auto-migration: {e}")
