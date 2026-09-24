import sqlite3
from pathlib import Path

# Cesta k databázi v podadresáři data/
DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "jobs.db"

def init_db():
    # Zajistí existenci složky data/
    DB_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabulka pro inzeráty
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            location TEXT,
            description TEXT NOT NULL,
            source TEXT NOT NULL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'NEW',  -- NEW, EVALUATED, GENERATED, APPLIED, REJECTED
            fit_score INTEGER DEFAULT NULL,
            fit_reasoning TEXT DEFAULT NULL
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"Databáze úspěšně inicializována v: {DB_PATH}")

if __name__ == "__main__":
    init_db()