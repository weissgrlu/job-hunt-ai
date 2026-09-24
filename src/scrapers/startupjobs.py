[System.IO.File]::WriteAllText("src/scrapers/jobscz.py", @"
import requests
from bs4 import BeautifulSoup

URL = "https://www.jobs.cz/prace/?q%5B%5D=data%20analyst"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8"
}

print("Stahuji nabidky z Jobs.cz...")
response = requests.get(URL, headers=headers)
print(f"Status kod: {response.status_code}")

soup = BeautifulSoup(response.text, "html.parser")

articles = soup.find_all("article")
print(f"Nalezeno {len(articles)} inzeratu.")

for i, article in enumerate(articles[:5], 1):
    link = article.find("a")
    title = link.get_text(strip=True) if link else "Bez nazvu"
    print(f"{i}. {title}")
"@, [System.Text.Encoding]::UTF8)