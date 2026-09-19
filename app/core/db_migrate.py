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

        # Relax NOT NULL constraint on users.phone and leads.phone if needed
        for t_name in ["users", "leads"]:
            if t_name in existing_tables:
                cursor.execute(f"PRAGMA table_info({t_name});")
                cols = cursor.fetchall()
                phone_col = next((c for c in cols if c[1] == "phone"), None)
                if phone_col and phone_col[3] == 1: # notnull == 1
                    logger.info(f"Migrating {t_name} table to make 'phone' column nullable...")
                    # Get table sql
                    cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t_name}';")
                    create_sql_row = cursor.fetchone()
                    if create_sql_row and create_sql_row[0]:
                        old_create_sql = create_sql_row[0]
                        # Replace 'phone VARCHAR(20) NOT NULL' or 'phone TEXT NOT NULL' with nullable
                        import re
                        new_create_sql = re.sub(r'(\bphone\s+[A-Za-z0-9_()]+)\s+NOT\s+NULL', r'\1', old_create_sql, flags=re.IGNORECASE)
                        if new_create_sql != old_create_sql:
                            temp_table = f"{t_name}_old_backup"
                            cursor.execute("PRAGMA foreign_keys=OFF;")
                            cursor.execute(f"ALTER TABLE {t_name} RENAME TO {temp_table};")
                            # Create new table with updated sql
                            cursor.execute(new_create_sql)
                            # Copy common columns
                            cursor.execute(f"PRAGMA table_info({temp_table});")
                            old_col_names = [r[1] for r in cursor.fetchall()]
                            cursor.execute(f"PRAGMA table_info({t_name});")
                            new_col_names = [r[1] for r in cursor.fetchall()]
                            common_cols = [c for c in old_col_names if c in new_col_names]
                            cols_str = ", ".join(common_cols)
                            cursor.execute(f"INSERT INTO {t_name} ({cols_str}) SELECT {cols_str} FROM {temp_table};")
                            cursor.execute(f"DROP TABLE {temp_table};")
                            cursor.execute("PRAGMA foreign_keys=ON;")
                            logger.info(f"Successfully migrated {t_name} table: 'phone' is now nullable.")
        
        conn.commit()
        conn.close()
        logger.info("SQLite auto-migration completed successfully.")
    except Exception as e:
        logger.error(f"Error during SQLite auto-migration: {e}")
