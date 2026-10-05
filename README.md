# JobHunt AI: End-to-End Automated Job Intelligence Pipeline

Plně autonomní datová a aplikační pipeline navržená pro kontinuální monitoring českého technologického trhu práce, sémantické vyhodnocování relevance pozic pomocí velkých jazykových modelů (LLM) a automatické generování vysoce personalizovaných, jednostránkových PDF životopisů a motivačních dopisů na míru.

Systém operuje bez nutnosti manuální asistence: pravidelně se spouští v definovaný čas přes Windows Task Scheduler, filtruje pozice splňující tvrdá kritéria shody ($\ge 70\,\%$) a odesílá kompletní denní briefing přímo do e-mailové schránky.

---

## Architektura systému

```text
[Jobs.cz & StartupJobs] 
         │ (Headless Chromium / Playwright & BeautifulSoup4)
         ▼
[Sběr inzerátů & Normalizace] ──► [SQLite DB (jobs.db)]
                                          │
         ┌────────────────────────────────┘
         ▼
[Gatekeeper Evaluator] ──► LLM scoring shody (0–100 %) & extrakce klíčových požadavků
         │
         ├─ (Fit Score < 70 %)  ──► Označeno jako EVALUATED (archivováno bez akce)
         │
         └─ (Fit Score >= 70 %) ──► [Tailored Generation Pipeline]
                                          │
                                          ├─ Dynamické TeX CV (Fira Sans / Tectonic engine)
                                          │   └─ Statický stack + cílená projektová odrážka na míru
                                          ├─ Personalizovaný motivační dopis (3 odstavce)
                                          │
                                          ▼
                                   [Status: GENERATED]
                                          │
                                          ▼
                                 [SMTP Notifikace] ──► Denní e-mailový briefing
```

---

## Klíčové vlastnosti

- **Multi-source Headless Scraping (`src/scrapers/`):**
  - Paralelní sběr nabídek z portálů **Jobs.cz** a **StartupJobs** s využitím headless prohlížeče Playwright (Chromium) pro spolehlivé načítání dynamického JavaScriptového obsahu.
  - Normalizace URL a textů, filtrace systémového balastu a deduplikace entit v SQLite databázi bránící opakovanému zpracování stejných nabídek.

- **Deterministické sémantické hodnocení (`src/evaluator.py`):**
  - Evaluace shody kandidáta s požadavky pozice (Fit Score 0–100 %) pomocí Google Gemini API.
  - Vynucené strukturované Pydantic schéma eliminující halucinace a extrahující klíčové technologie role (SQL, Python, BI, cloudové platformy, matematika/statistika).

- **Dvoufázová personalizace CV bez redundancí (`src/generator.py`):**
  - **Architektura odrážek:** Každý projekt v CV kombinuje pevnou větu popisující architekturu/stack a jednu striktně dynamickou odrážku.
  - LLM dynamicky vybírá a formuluje konkrétní technický detail (např. optimalizace BigQuery dotazů vs. regex parsování METARu vs. orchestrace procesů) podle toho, co poptává daný inzerát.
  - Profesní shrnutí v záhlaví CV propojuje matematicko-statistický základ (MFF UK) s konkrétním zaměřením role.

- **Deterministická sazba přes Tectonic (`src/generator.py`):**
  - Automatická kompilace LaTeXové šablony (`cv_template.tex`) do typograficky čistého jednostránkového PDF přes moderní kompilátor **Tectonic**.
  - Ošetření speciálních znaků LaTeXu a podpora české diakritiky s písmem **Fira Sans**.

- **Robustní workflow & správa stavů:**
  - Životní cyklus inzerátu v databázi: `NEW` ➔ `EVALUATED` ➔ `GENERATED` ➔ `APPLIED`.
  - Zabudovaný exponential backoff a prodlevy chránící pipeline před vyčerpáním API limitů (RPM).
  - SMTP modul odesílá přehledný e-mailový souhrn pouze v případě vzniku nových relevantních nabídek.

---

## Technický stack

- **Jazyk a logika:** Python 3.11+, Playwright, BeautifulSoup4, Pydantic v2
- **Databáze:** SQLite3
- **Typografie a sazba:** LaTeX, Tectonic CLI, Fira Sans
- **AI Integrace:** Google Gemini API (`gemini-flash-lite-latest` / strukturovaný JSON režim)
- **Orchestrace & OS:** Windows Task Scheduler, PowerShell, SMTP

---

## Struktura projektu

```text
job-hunt-ai/
├── data/
│   ├── applications/      # Vygenerované složky (cv.pdf, cv.tex, pruvodni_dopis.txt)
│   ├── cv_template.tex    # LaTeXová šablona s placeholdery pro dynamický obsah
│   ├── profile.json       # Strukturovaný profil kandidáta (vzdělání, stack, projekty)
│   └── jobs.db            # SQLite databáze inzerátů, skóre a aplikačních stavů
├── src/
│   ├── scraper_jobs.py    # Scraping a extrakce z Jobs.cz
│   ├── scraper_startup.py # Scraping a extrakce ze StartupJobs
│   ├── evaluator.py       # Gatekeeper scoring a relevance inzerátů
│   ├── generator.py       # Generování textů na míru a kompilace PDF
│   └── notifier.py        # SMTP distribuce e-mailových briefingů
├── main.py                # Centrální orchestrátor celé pipeline
├── .env                   # API klíče a přihlašovací údaje pro SMTP (necommitovat)
└── README.md
```

---

## Instalace a nastavení

### 1. Inicializace prostředí a instalace závislostí
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 2. Konfigurace proměnných prostředí (`.env`)
V kořenovém adresáři vytvořte soubor `.env`:
```env
GEMINI_API_KEY=vase_gemini_api_key
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=vas_email@gmail.com
SMTP_PASSWORD=vase_aplikacni_heslo
NOTIFICATION_RECIPIENT=vas_email@gmail.com
```

### 3. Spuštění pipeline
Manuální spuštění celého řetězce (scraping, scoring, generování PDF a odeslání mailu):
```powershell
python main.py
```

### 4. Automatizace (Windows Task Scheduler)
Pro plně bezobslužný denní běh (např. v 18:00):
1. Vytvořte novou základní úlohu v Plánovači úloh Windows.
2. Nastavte spouštění programu: `C:\job-hunt-ai\venv\Scripts\python.exe`
3. Přidejte argument: `main.py`
4. Pole **Spustit v (Start in)** nastavte na kořen projektu: `C:\job-hunt-ai`
5. V záložce *Podmínky* zaškrtněte možnost *Probudit počítač k provedení této úlohy*.
