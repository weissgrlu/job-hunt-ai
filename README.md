# JobHunt AI: End-to-End Automated Job Intelligence Pipeline

Plně automatizovaný systém navržený pro kontinuální monitoring trhu práce, sémantické vyhodnocování relevance nabídek pomocí LLM a autonomní generování přihlášek (strukturované PDF životopisy a motivační dopisy na míru) bez nutnosti manuální asistence.

Systém běží samostatně v definovaném denním čase na bázi plánovače úloh s probuzením hardwaru a odesílá reporty s vygenerovanými podklady přímo do e-mailové schránky.

---

## Architektura systému

```text
[Jobs.cz Search] 
       │ (HTTP GET / BeautifulSoup4)
       ▼
[Nové inzeráty & Metadata] ──► [SQLite DB (jobs.db)]
                                     │
       ┌─────────────────────────────┘
       ▼
[Detail Parsing] ──► Extrakce kompletního těla inzerátu (redirecty, EN nabídky)
       │
       ▼
[Gatekeeper Evaluator] ──► LLM scoring shody (0–100 %) & extrakce klíčových požadavků
       │
       ├─ (Score < 70)  ──► Archivováno bez akce
       │
       └─ (Score >= 70) ──► [Generování materiálů na míru]
                                 │
                                 ├─ Dynamické TeX CV (Fira Sans / Tectonic engine)
                                 ├─ Personalizovaný motivační dopis (Markdown)
                                 │
                                 ▼
                           [SMTP Notifikace] ──► Denní e-mailový briefing
```

---

## Klíčové vlastnosti

- **Dvoufázový scraping & normalizace (`src/scrapers/jobscz.py`):**
  - Vyhledávání a sběr nových inzerátů z Jobs.cz podle definovaných klíčových dotazů (`data analyst`, `business analyst`, `bi analyst`).
  - Dávkové dotahování plných textů nabídek s ošetřením přesměrování a čištěním navigačního balastu.
  - Automatická deduplikace záznamů v SQLite na základě normalizovaného názvu pozice a společnosti; filtrace systémových odkazů (GDPR, cookie policy).

- **Deterministické LLM vyhodnocení (`src/evaluator.py`):**
  - Kvantifikace shody kandidáta s požadavky pozice (Fit Score 0–100) zaměřené na analytický stack (SQL, Python, BI, data storytelling, modelování).
  - Vynucený strukturovaný JSON výstup eliminující halucinace.

- **Dynamická typografie a kompilace PDF (`src/generator.py`):**
  - Přizpůsobení profesního shrnutí a projektových odrážek specifikům každé pozice.
  - Přímá kompilace LaTeXové šablony do jednostránkového PDF pomocí moderního enginu **Tectonic**.
  - Ošetření české diakritiky a bezpatkového fontu pomocí balíčku **Fira Sans**.

- **Bezúdržbový běh (Autopilot):**
  - Spouštění přes Windows Task Scheduler v kombinaci s `RTC Wake Timers` (úloha probudí uspaný počítač v 18:00, provede pipeline a systém se následně opět uspí).
  - Přímé doručování výsledků a nově vygenerovaných materiálů na e-mail přes SMTP.

---

## Použité technologie

- **Jazyk a logika:** Python 3.11+, Requests, BeautifulSoup4
- **Databáze:** SQLite3
- **Typografie & Kompilace:** LaTeX, Tectonic CLI, Fira Sans
- **Orchestrace & Systém:** Windows Task Scheduler, RTC Wake Timers, Batch Scripting
- **AI Integrace:** Google Gemini API (strukturovaná inference)

---

## Struktura projektu

```text
job-hunt-ai/
├── data/
│   ├── applications/      # Složky s vygenerovanými CV (PDF/TeX) a dopisy (MD)
│   ├── cv_template.tex    # LaTeXová šablona s Fira Sans
│   └── jobs.db            # SQLite databáze inzerátů a stavů
├── src/
│   ├── scrapers/
│   │   └── jobscz.py      # Sběr dat, dotahování textů a deduplikace
│   ├── evaluator.py       # LLM logika a filtrace pozic
│   ├── generator.py       # Tvorba přizpůsobených TeX šablon a dopisů
│   └── notifier.py        # E-mailová distribuce
├── main.py                # Hlavní řídicí orchestrátor pipeline
├── run_pipeline.bat       # Dávkový skript pro plánovač úloh
└── README.md
```

---

## Instalace a spuštění

### 1. Inicializace virtuálního prostředí
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Spuštění celé pipeline ručně
```powershell
python main.py
```

### 3. Konfigurace denní automatizace
Úloha je navržena pro automatické spouštění souborem `run_pipeline.bat` přes Windows Task Scheduler s parametrem `-WakeToRun`.