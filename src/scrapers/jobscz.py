import hashlib
import sqlite3
import time
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
    return url.split("?")[0].strip()

def generate_job_id(clean_url_str: str) -> str:
    return hashlib.md5(clean_url_str.encode("utf-8")).hexdigest()

def fetch_job_detail(job_url: str) -> str:
    """Stahne samotnou stranku inzeratu a vytahne cisty text popisu prace."""
    try:
        res = requests.get(job_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return ""
        
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Hledame hlavni kontejner s textem inzeratu
        # Na Jobs.cz/Prace.cz byva text typicky v <main> nebo specifickych div sekcich
        main_content = soup.find("main") or soup.find("div", class_="StandalonePage")
        
        if main_content:
            # Odstranime nepotrebne skripty a styly
            for tag in main_content(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = main_content.get_text(separator="\n", strip=True)
            return text[:4000] # Ulozime maximalne 4000 znaku pro LLM
            
        return soup.get_text(separator="\n", strip=True)[:4000]
    except Exception as e:
        print(f"Varovani: Nepodarilo se stahnout detail pro {job_url}: {e}")
        return ""

def scrape_jobs(max_details_to_fetch: int = 5):
    print("1. Stahuji prehled nabidek z Jobs.cz...")
    response = requests.get(URL, headers=HEADERS)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.find_all("article")
    print(f"2. Nalezeno {len(articles)} inzeratu k analyze.")
    
    parsed_jobs = []
    # Pro test stahneme detaily jen k prvnim nekolika nabidkam
    details_fetched = 0
    
    for article in articles:
        link_tag = article.find("a")
        if not link_tag or not link_tag.get("href"):
            continue
            
        raw_url = link_tag["href"]
        if not raw_url.startswith("http"):
            raw_url = f"https://www.jobs.cz{raw_url}"
            
        job_url = clean_url(raw_url)
        title = link_tag.get_text(strip=True)
        job_id = generate_job_id(job_url)
        
        # Stazeni plneho textu inzeratu
        description = title
        if details_fetched < max_details_to_fetch:
            print(f"   -> Stahuji detail pozice: {title[:40]}...")
            detail_text = fetch_job_detail(job_url)
            if detail_text:
                description = detail_text
            details_fetched += 1
            time.sleep(1) # Zdvurila pauza 1 sekunda mezi pozadavky
            
        parsed_jobs.append({
            "id": job_id,
            "title": title,
            "company": "Jobs.cz inzerent",
            "url": job_url,
            "location": "Ceska republika",
            "description": description,
            "source": "Jobs.cz"
        })
        
    return parsed_jobs

def save_to_database(jobs: list):
    print("3. Ukladam do SQLite databaze...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    new_jobs_count = 0
    updated_details_count = 0
    
    for job in jobs:
        # Zkusime nejprve vlozit novy zaznam
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
            # Pokud uz inzerat existuje, ale ziskali jsme k nemu detailnejsi popis nez puvodni kratky
            if len(job["description"]) > 100:
                cursor.execute("""
                    UPDATE jobs 
                    SET description = ? 
                    WHERE id = ? AND length(description) < 100
                """, (job["description"], job["id"]))
                if cursor.rowcount > 0:
                    updated_details_count += 1
            
    conn.commit()
    conn.close()
    return new_jobs_count, updated_details_count

if __name__ == "__main__":
    jobs = scrape_jobs(max_details_to_fetch=3)
    new_count, updated_count = save_to_database(jobs)
    print(f"Hotovo! Pridano {new_count} novych, aktualizovano {updated_count} detailu.")