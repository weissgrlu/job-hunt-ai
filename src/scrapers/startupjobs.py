import logging
import sqlite3
import time
import re
import unicodedata
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "data/jobs.db"

SEARCH_TERMS = ["data analyst", "datovy analytik", "business intelligence", "BI", "SQL"]
BASE_URL = "https://www.startupjobs.cz/nabidky"


def init_db(db_path: str = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def save_job(url: str, title: str, company: str, description: str, db_path: str = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO jobs (url, title, company, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                company = CASE 
                    WHEN excluded.company != 'Neznámá společnost' THEN excluded.company 
                    ELSE jobs.company 
                END,
                description = excluded.description
        """, (url, title, company, description))
        conn.commit()


def normalize_text(text: str) -> str:
    """Odstraní diakritiku, interpunkci, právní formy a převede na malá písmena."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    
    # Odstranění běžných právních forem
    text = re.sub(r"\b(s\.r\.o\.|spol\. s r\.o\.|a\.s\.|as|sro|gmbh|inc|llc)\b", "", text)
    # Odstranění textu v závorkách (m/ž, lokality atd.)
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", "", text)
    # Ponechání pouze alfanumerických znaků
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def is_duplicate_job(conn, title: str, company: str) -> bool:
    """Ověří, zda v DB již neexistuje velmi podobný inzerát od stejné firmy."""
    norm_title = normalize_text(title)
    norm_comp = normalize_text(company)

    if not norm_comp or norm_comp == "neznama spolecnost":
        return False

    cursor = conn.cursor()
    cursor.execute("SELECT title, company FROM jobs")
    rows = cursor.fetchall()

    for db_title, db_comp in rows:
        db_norm_comp = normalize_text(db_comp)
        if db_norm_comp and (norm_comp in db_norm_comp or db_norm_comp in norm_comp):
            db_norm_title = normalize_text(db_title)
            if norm_title == db_norm_title or norm_title in db_norm_title or db_norm_title in norm_title:
                return True
                
    return False


def extract_startupjobs_links(page) -> list[dict]:
    soup = BeautifulSoup(page.content(), "html.parser")
    found_jobs = []

    for a_tag in soup.select("a[href*='/nabidka/']"):
        href = a_tag.get("href", "")
        if not href:
            continue

        full_url = f"https://www.startupjobs.cz{href}" if href.startswith("/") else href
        clean_url = full_url.split("?")[0]

        title_el = a_tag.select_one("h2, h3, [class*='title'], [class*='Title']")
        title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)

        company_el = a_tag.select_one("[class*='company'], [class*='Company'], [class*='author']")
        company = company_el.get_text(strip=True) if company_el else "Neznámá společnost"

        if title and len(title) > 3:
            found_jobs.append({
                "url": clean_url,
                "title": title,
                "company": company
            })

    return list({j["url"]: j for j in found_jobs}.values())


def scrape_startupjobs():
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        existing_urls = set(
            row[0] for row in conn.execute(
                "SELECT url FROM jobs WHERE description IS NOT NULL AND LENGTH(description) > 200"
            ).fetchall()
        )

    with sync_playwright() as p:
        logger.info("[StartupJobs] Spouštím Chromium...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="cs-CZ"
        )
        page = context.new_page()

        collected = []

        for term in SEARCH_TERMS:
            search_url = f"{BASE_URL}?superSearch={quote_plus(term)}"
            logger.info(f"[StartupJobs] Hledám výraz: '{term}' -> {search_url}")

            try:
                page.goto(search_url, wait_until="networkidle", timeout=25000)
                page.evaluate("window.scrollBy(0, 1200)")
                time.sleep(1.5)

                jobs = extract_startupjobs_links(page)
                logger.info(f" -> Nalezeno {len(jobs)} karet.")
                collected.extend(jobs)
            except Exception as e:
                logger.warning(f"Chyba při vyhledávání '{term}': {e}")

        unique_jobs = list({j["url"]: j for j in collected}.values())
        new_jobs = [j for j in unique_jobs if j["url"] not in existing_urls]
        logger.info(f"[StartupJobs] Celkem unikátních: {len(unique_jobs)}, nových ke stažení: {len(new_jobs)}")

        # Stažení detailů inzerátů s kontrolou duplicit
        with sqlite3.connect(DB_PATH) as conn:
            for idx, job in enumerate(new_jobs, start=1):
                job_url = job["url"]

                # 1. Kontrola duplicity z již stažených nabídek (např. z Jobs.cz)
                if is_duplicate_job(conn, job["title"], job["company"]):
                    logger.info(f"[{idx}/{len(new_jobs)}] Přeskakuji duplikát: {job['company']} - {job['title']}")
                    continue

                logger.info(f"[{idx}/{len(new_jobs)}] Stahuji detail: {job['title']}")

                try:
                    page.goto(job_url, wait_until="networkidle", timeout=20000)
                    
                    company = job["company"]
                    if company == "Neznámá společnost":
                        page_title = page.title()
                        parts = [p.strip() for p in page_title.split("|") if "StartupJobs" not in p]
                        if len(parts) >= 2:
                            company = parts[-1]

                    # Druhá kontrola duplicity, pokud jsme firmu zjistili až z titulku detailu
                    if is_duplicate_job(conn, job["title"], company):
                        logger.info(f" -> Duplikát odhalen po zjištění firmy ({company}), neukládám.")
                        continue

                    raw_text = page.inner_text("body")
                    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
                    clean_description = "\n".join(lines)

                    save_job(
                        url=job_url,
                        title=job["title"],
                        company=company,
                        description=clean_description
                    )
                except Exception as e:
                    logger.warning(f"Chyba při stahování {job_url}: {e}")

                time.sleep(0.6)

        browser.close()
        logger.info("[StartupJobs] Scraping dokončen.")


if __name__ == "__main__":
    scrape_startupjobs()