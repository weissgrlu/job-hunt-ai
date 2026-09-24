import hashlib
import sqlite3
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT_DIR / "data" / "jobs.db"

URL = "https://www.jobs.cz/prace/?q%5B%5D=data%20analyst"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
}

def clean_url(url: str) -> str:
    """Odstrani sledovaci parametry za otaznikem."""
    return url.split("?")[0].strip()

def generate_job_id(clean_url_str: str) -> str:
    """Vytvori unikatni MD5 hash z ocistene URL adresy."""
    return hashlib.md5(clean_url_str.encode("utf-8")).hexdigest()

def scrape_jobs():
    print("1. Stahuji stranku z Jobs.cz...")
    response = requests.get(URL, headers=HEADERS)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.find_all("article")
    print(f"2. Nalezeno {len(articles)} inzeratu k analyze.")
    
    parsed_jobs = []
    for article in articles:
        link_tag = article.find("a")
        if not link_tag or not link_tag.get("href"):
            continue
            
        raw_url = link_tag["href"]
        if not raw_url.startswith("http"):
            raw_url = f"https://www.jobs.cz{raw_url}"
            
        # Očistíme URL od balastu za otazníkem
        job_url = clean_url(raw_url)
        title = link_tag.get_text(strip=True)
        job_id = generate_job_id(job_url)
        
        parsed_jobs.append({
            "id": job_id,
            "title": title,
            "company": "Jobs.cz inzerent",
            "url": job_url,
            "location": "Ceska republika",
            "description": title,
            "source": "Jobs.cz"
        })
        
    return parsed_jobs

def save_to_database(jobs: list):
    print("3. Ukladam do SQLite databaze...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    new_jobs_count = 0
    for job in jobs:
        try:
            cursor.execute("""
                INSERT INTO jobs (id, title, company, url, location, description, source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW')
            """, (
                job["id"],
                job["title"],
                job["company"],
                job["url"],
                job["location"],
                job["description"],
                job["source"]
            ))
            new_jobs_count += 1
        except sqlite3.IntegrityError:
            continue
            
    conn.commit()
    conn.close()
    return new_jobs_count

if __name__ == "__main__":
    jobs = scrape_jobs()
    inserted = save_to_database(jobs)
    print(f"Hotovo! Nove pridano {inserted} unikatnich inzeratu do databaze.")