import hashlib
import random
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT_DIR / "data" / "jobs.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs,en-US;q=0.9,en;q=0.8",
}

# Hledané pozice na Jobs.cz
SEARCH_QUERIES = [
    "data analyst",
    "business analyst",
    "bi analyst"
]


def init_db():
    """Zajistí existenci tabulky jobs."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            company TEXT,
            location TEXT,
            url TEXT UNIQUE,
            description TEXT,
            fit_score INTEGER,
            status TEXT DEFAULT 'NEW',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def normalize_string(text: str) -> str:
    """Normalizuje text pro porovnání duplicit (odstraní diakritiku, převede na malá písmena)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def scrape_jobs(max_pages_per_query: int = 3):
    """Prohledá Jobs.cz pro zadané dotazy a nové inzeráty uloží do DB."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    total_added = 0
    print(f"Spouštím scraping vyhledávání na Jobs.cz pro dotazy: {', '.join(SEARCH_QUERIES)}...")

    for query in SEARCH_QUERIES:
        for page in range(1, max_pages_per_query + 1):
            url = f"https://www.jobs.cz/prace/?q={requests.utils.quote(query)}&page={page}"
            try:
                time.sleep(random.uniform(1.0, 2.0))
                res = requests.get(url, headers=HEADERS, timeout=15)
                if res.status_code != 200:
                    break

                soup = BeautifulSoup(res.content, "html.parser")
                articles = soup.find_all("article")
                if not articles:
                    # Alternativní selektory pro výpis inzerátů
                    articles = soup.select(".SearchResultCard, [data-job-id]")

                if not articles:
                    break

                added_in_page = 0
                for art in articles:
                    link_tag = art.find("a", href=re.compile(r"/rpd/|/fp/|/pd/"))
                    if not link_tag:
                        continue

                    job_url = urljoin("https://www.jobs.cz", link_tag.get("href", "").split("?")[0])
                    title = link_tag.get_text(strip=True)
                    if not title or not job_url:
                        continue

                    # Získání firmy a lokality, pokud jsou dostupné
                    company = "Neuvedeno"
                    comp_elem = art.find(class_=re.compile(r"company|f-bold", re.I))
                    if comp_elem:
                        company = comp_elem.get_text(strip=True)

                    location = "Česká republika"
                    loc_elem = art.find(class_=re.compile(r"locality|location|f-italic", re.I))
                    if loc_elem:
                        location = loc_elem.get_text(strip=True)

                    try:
                        cursor.execute("""
                            INSERT INTO jobs (title, company, location, url, status)
                            VALUES (?, ?, ?, ?, 'NEW')
                        """, (title, company, location, job_url))
                        conn.commit()
                        added_in_page += 1
                        total_added += 1
                    except sqlite3.IntegrityError:
                        # Inzerát už v DB existuje podle URL
                        continue

                print(f" -> Dotaz '{query}' (strana {page}): nalezeno {len(articles)} inzerátů, nových přidáno: {added_in_page}")

            except Exception as e:
                print(f"Chyba při stahování {url}: {e}")
                break

    conn.close()
    print(f"Scraping dokončen. Celkem nově přidáno do DB: {total_added} inzerátů.")


def fetch_job_detail(url: str) -> str:
    """Stáhne detail inzerátu s podporou redirectů a různých HTML struktur."""
    try:
        time.sleep(random.uniform(0.6, 1.2))
        session = requests.Session()
        res = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if res.status_code != 200:
            return ""

        soup = BeautifulSoup(res.content, "html.parser")

        # Odstranění technického a navigačního balastu
        for junk in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            junk.extract()

        candidates = [
            soup.find("div", class_=re.compile(r"job-ad-body|standalone-content|cp-body|typography", re.I)),
            soup.find("section", class_=re.compile(r"job-ad|content", re.I)),
            soup.find("main"),
            soup.body,
        ]

        main_elem = next((c for c in candidates if c is not None), soup)

        text_elements = main_elem.find_all(["p", "li", "h1", "h2", "h3", "h4", "div"])
        full_text = " ".join([elem.get_text(separator=" ", strip=True) for elem in text_elements])
        cleaned = re.sub(r"\s+", " ", full_text).strip()

        return cleaned[:5000] if len(cleaned) > 80 else ""
    except Exception:
        return ""


def clean_database_duplicates():
    """Odstraní duplicity a systémové/GDPR odkazy přímo z databáze."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Odstranění GDPR a technických odkazů
    cursor.execute("""
        DELETE FROM jobs 
        WHERE lower(url) LIKE '%gdpr%' 
           OR lower(title) LIKE '%gdpr%'
           OR lower(url) LIKE '%cookies%'
           OR lower(url) LIKE '%terms%'
    """)

    # 2. Odstranění duplicit podle normalizované firmy a pozice
    cursor.execute("""
        DELETE FROM jobs 
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, 
                       ROW_NUMBER() OVER (
                           PARTITION BY lower(trim(company)), lower(trim(title)) 
                           ORDER BY fit_score DESC, length(ifnull(description, '')) DESC, id DESC
                       ) as rn 
                FROM jobs
            ) WHERE rn = 1
        )
    """)

    conn.commit()
    conn.close()


def enrich_missing_details(limit: int = 200):
    clean_database_duplicates()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url 
        FROM jobs 
        WHERE (description IS NULL OR length(description) <= 100)
          AND lower(url) NOT LIKE '%gdpr%'
          AND lower(title) NOT LIKE '%gdpr%'
        LIMIT ?
    """, (limit,))

    jobs_without_detail = cursor.fetchall()

    if not jobs_without_detail:
        print("Všechny inzeráty v databázi již mají plný detail.")
        conn.close()
        return

    print(f"Dotahuji detaily pro {len(jobs_without_detail)} inzerátů (včetně EN / redirectů)...")

    for idx, (job_id, title, url) in enumerate(jobs_without_detail, start=1):
        print(f"[{idx}/{len(jobs_without_detail)}] Stahuji: {title[:50]}...")
        detail_text = fetch_job_detail(url)

        if detail_text:
            cursor.execute("UPDATE jobs SET description = ? WHERE id = ?", (detail_text, job_id))
            conn.commit()
        else:
            print(f" -> Detail se nepodařilo načíst: {title[:40]}")

    conn.close()
    print("\nDotahování detailů dokončeno.")


if __name__ == "__main__":
    scrape_jobs()
    enrich_missing_details()