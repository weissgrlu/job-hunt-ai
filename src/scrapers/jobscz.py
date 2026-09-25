import logging
import sqlite3
import time
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "data/jobs.db"

# Hledané výrazy pro datové a BI role
SEARCH_TERMS = [
    "datový analytik",
    "data analyst",
    "BI analytik",
    "business intelligence",
    "reporting analyst",
    "SQL analytik",
    "junior data"
]

QUERY_STRING = "&".join(f"q%5B%5D={quote_plus(term)}" for term in SEARCH_TERMS)
BASE_SEARCH_URL = f"https://www.jobs.cz/prace/praha/?{QUERY_STRING}"


def init_db(db_path: str = DB_PATH) -> None:
    """Vytvoří tabulku v SQLite, pokud ještě neexistuje."""
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
    """Uloží nebo aktualizuje záznam inzerátu v SQLite databázi."""
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


def extract_job_links(page_html: str) -> list[dict]:
    """Z HTML stránky výsledků vyhledávání vytáhne odkazy, názvy a firmy."""
    soup = BeautifulSoup(page_html, "html.parser")
    jobs = []

    for article in soup.select("article.SearchResultCard, div[data-job-id]"):
        link_tag = article.select_one("a.SearchResultCard__titleLink, a[href*='/rpd/'], a[href*='detail-pozice']")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        if not href.startswith("http"):
            href = f"https://www.jobs.cz{href}"

        title = link_tag.get_text(strip=True)

        # Robustní hledání názvu firmy přes více možných selektorů na Jobs.cz
        company = "Neznámá společnost"
        company_tag = article.select_one(
            ".SearchResultCard__author, "
            ".SearchResultCard__footerMeta span, "
            "[data-qa='company-name'], "
            "[data-qa='search-result-company'], "
            "a[href*='/spolecnost/'], "
            ".SearchResultCard__companyName"
        )

        if company_tag:
            cand = company_tag.get_text(strip=True)
            if cand and not any(skip in cand.lower() for skip in ["před", "dny", "hodin", "kč", "praha"]):
                company = cand

        clean_url = href if "detail-pozice" in href else href.split("?")[0]

        jobs.append({
            "url": clean_url,
            "title": title,
            "company": company
        })

    return jobs


def parse_company_from_title(page_title: str) -> str:
    """Zkusí vytáhnout firmu z titulku stránky (např. 'Datový analytik – ABC s.r.o. | Jobs.cz')."""
    if not page_title:
        return ""
    # Ořízneme suffix '| Jobs.cz' nebo '- Jobs.cz'
    clean_t = re.sub(r"\s*[\|\-–—]\s*Jobs\.cz.*$", "", page_title, flags=re.IGNORECASE).strip()
    # Rozdělíme podle pomlčky
    parts = re.split(r"\s+[–—\-]\s+", clean_t)
    if len(parts) >= 2:
        return parts[-1].strip()
    return ""


def run_scraper(search_url: str = BASE_SEARCH_URL, max_pages: int = 3) -> None:
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        existing_urls = set(
            row[0] for row in conn.execute(
                "SELECT url FROM jobs WHERE description IS NOT NULL AND LENGTH(description) > 200"
            ).fetchall()
        )

    with sync_playwright() as p:
        logger.info("Spouštím headless Chromium...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="cs-CZ"
        )
        page = context.new_page()

        collected_jobs = []

        # 1. Procházení stránek vyhledávání
        for page_num in range(1, max_pages + 1):
            url = f"{search_url}&page={page_num}" if page_num > 1 else search_url
            logger.info(f"Procházím stránku vyhledávání {page_num}: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                jobs_on_page = extract_job_links(page.content())
                logger.info(f"Nalezeno {len(jobs_on_page)} inzerátů na stránce {page_num}.")

                if not jobs_on_page:
                    break

                collected_jobs.extend(jobs_on_page)
            except Exception as e:
                logger.error(f"Chyba při čtení stránky {page_num}: {e}")
                break

        unique_jobs = list({job["url"]: job for job in collected_jobs}.values())
        new_jobs = [job for job in unique_jobs if job["url"] not in existing_urls]
        logger.info(f"Nalezeno {len(unique_jobs)} inzerátů celkem. Z toho nových ke stažení: {len(new_jobs)}")

        # 2. Stažení detailu pouze pro nové pozice
        for idx, job in enumerate(new_jobs, start=1):
            job_url = job["url"]
            company_name = job["company"]

            try:
                page.goto(job_url, wait_until="networkidle", timeout=20000)
                raw_text = page.inner_text("body")

                # Fallback pro firmu z titulku otevřené stránky
                if company_name == "Neznámá společnost":
                    page_title = page.title()
                    extracted_comp = parse_company_from_title(page_title)
                    if extracted_comp:
                        company_name = extracted_comp

                logger.info(f"[{idx}/{len(new_jobs)}] Stahuji detail: {job['title']} | {company_name}")

                lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
                clean_description = "\n".join(lines)

                save_job(
                    url=job_url,
                    title=job["title"],
                    company=company_name,
                    description=clean_description
                )
            except Exception as e:
                logger.warning(f"Chyba při stahování detailu {job_url}: {e}")

            time.sleep(0.5)

        browser.close()
        logger.info("Scraping fáze dokončena.")


scrape_jobs = run_scraper

def enrich_missing_details(*args, **kwargs) -> None:
    pass


if __name__ == "__main__":
    run_scraper()