import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "jobs.db"
PROFILE_PATH = ROOT_DIR / "data" / "profile.json"
CV_TEMPLATE_PATH = ROOT_DIR / "data" / "cv_template.tex"
APPLICATIONS_DIR = ROOT_DIR / "data" / "applications"

load_dotenv(ROOT_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("Chyba: GEMINI_API_KEY nebyl nalezen v .env!")

client = genai.Client(api_key=API_KEY)


class TailoredContent(BaseModel):
    cv_summary: str = Field(
        description="Profesní shrnutí (2-3 věty) do záhlaví CV v češtině. Zdůrazni exaktní analytické základy z MFF UK, praktické ovládání SQL/Python/BI a věcnou orientaci na řešení reálných byznys problémů bez klišé. Přizpůsob tón a zdůrazněné technologie poptávané roli v inzerátu."
    )
    jobhunt_project_bullet: str = Field(
        description="Konkrétní technický detail k projektu JobHunt AI (přesně 1 věta v češtině). NIKDY nepopisuj celý projekt ani nezačínej 'V projektu...'. Zdůrazni konkrétní technický aspekt odpovídající poptávce v inzerátu: např. normalizační logiku v SQLite, regex čištění textu, ošetření API rate-limitů s backoffem nebo orchestraci procesů přes Task Scheduler."
    )
    flight_project_bullet: str = Field(
        description="Konkrétní analytický detail k projektu leteckých zpoždění (přesně 1 věta v češtině). NIKDY nepopisuj celý projekt ani nezačínej 'V projektu...'. Zdůrazni konkrétní aspekt relevantní pro danou pozici: např. sestavení regex parseru pro nestrukturované METAR depeše, trasování rotací letadel podle tail number, čištění chybějících hodnot v Pandas nebo návrh vizualizací v Tableau."
    )
    cyclistic_project_bullet: str = Field(
        description="Konkrétní byznys či datový detail k projektu Cyclistic (přesně 1 věta v češtině). NIKDY nepopisuj celý projekt ani nezačínej 'V projektu...'. Zdůrazni konkrétní aspekt podle zaměření role: např. optimalizace agregačních dotazů a partitioningu nad 5,9M řádky v BigQuery, kohortové srovnání špiček v chování předplatitelů nebo návrh hypotéz pro konverzní kampaně."
    )
    cover_letter_body: str = Field(
        description="Strukturovaný text motivačního dopisu (přesně 3 odstavce: 1. úvod a konkrétní motivace pro danou firmu/roli, 2. konkrétní přínos, technologie a relevance projektů, 3. závěr a výzva k osobnímu setkání). Tón je profesionální, věcný a sebevědomý, bez patosu a obecných klišé."
    )


def sanitize_folder_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "_", name)


def escape_latex(text: str) -> str:
    """Ošetří speciální znaky, aby nerozbily LaTeX překlad."""
    if not text:
        return ""
    chars = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    pattern = re.compile("|".join(re.escape(k) for k in chars.keys()))
    return pattern.sub(lambda m: chars[m.group()], text)


def load_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def generate_tailored_texts(profile_str: str, job_title: str, job_desc: str) -> TailoredContent:
    prompt = f"""
Jsi seniorní datový architekt a hiring manager. Tvým úkolem je připravit vysoce personalizované, věcné a technicky exaktní podklady pro kandidáta, které přesvědčí firmu, že má přesně ty schopnosti a myšlení, které hledají.

PROFIL KANDIDÁTA:
{profile_str}

POZICE: {job_title}
POPIS POZICE (INZERÁT):
{job_desc}

PRAVIDLA PRO GENEROVÁNÍ TEXTŮ:

1. `cv_summary` (2-3 věty):
   - Propoj exaktní základ z MFF UK (matematická analýza, statistika) s praktickou praxí v datech (SQL, Python, BI) a zkušenostmi z operativního řízení organizace.
   - Vyzdvihni ty nástroje a vlastnosti, které inzerát nejvíce poptává (pokud hledají BI, zdůrazni vizualizaci a byznys rozhodování; pokud hledají ETL/Python, zdůrazni automatizaci, scriptování a datové struktury).
   - Žádná prázdná klišé ("jsem nadšený", "hledám novou výzvu").

2. PROJEKTOVÉ ODRÁŽKY (PŘÍSNÁ PRAVIDLA PROTI REDUNDANCI):
   V životopise již existuje základní popis každého projektu! Tvá odrážka NESMÍ znovu popisovat, co projekt dělá, ani parafrázovat základní stack.
   - ZÁKAZ frází: "Vytvořil systém pro...", "Analyzoval data o...", "Navrhl pipeline pro...".
   - KAŽDÁ ODRÁŽKA MUSÍ BÝT PŘESNĚ 1 VĚTA, která začíná přímo akčním slovesem v minulém čase nebo konkrétní metodou (např. "Implementoval...", "Strukturoval...", "Zredukoval...", "Kombinací dotazů odhalil...").
   - Úkolem této jedné věty je vybrat JEDEN konkrétní technický nebo byznys detail z projektu, který odpovídá požadavkům v tomto konkrétním inzerátu:

   * `jobhunt_project_bullet` (JobHunt AI):
     - Zvol detail podle role: pokud inzerát hledá backend/DB, zdůrazni normalizovanou deduplikaci a transakce v SQLite. Pokud hledá API/AI, zdůrazni strukturované schema výstupů přes Gemini API a ošetření chyb. Pokud orchestraci, zmiň periodické plánování úloh a headless scraping.
   
   * `flight_project_bullet` (The Hidden Cost of Weather):
     - Zvol detail podle role: pokud inzerát hledá práci s textem/Pythonem, vypíchni regex parsování kódů meteorologických jevů z METAR. Pokud časové řady, vypíchni rekonstrukci rotací letadel podle registrace (tail number). Pokud reporting/BI, vypíchni metriky a dashboard v Tableau.
   
   * `cyclistic_project_bullet` (Cyclistic Bike-Share):
     - Zvol detail podle role: pokud inzerát řeší databáze/SQL, vypíchni optimalizaci dotazů nad 5,9M řádky v BigQuery. Pokud řeší byznys/marketing, vypíchni identifikaci rozdílů v chování předplatitelů a návrh cílení.

3. `cover_letter_body` (3 odstavce):
   - Odstavec 1: Úvodní oslovení, reakce na roli a stručné shrnutí, proč profil (matematika MFF UK + praktická datová praxe) přesně pasuje na potřeby firmy.
   - Odstavec 2: Konkrétní důkazy – propojení klíčových požadavků z inzerátu se zkušenostmi na projektech (zmínit konkrétní stack a relevantní výstupy).
   - Odstavec 3: Závěrečné shrnutí ochoty rychle se zapojit a přinést týmu exaktní výsledky + přímá výzva k osobnímu setkání.
   - Vynechej úvodní hlavičky typu "Vážený pane...", generuj pouze samotné tělo textu dopisu.
"""

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": TailoredContent,
        },
    )

    return TailoredContent.model_validate_json(response.text)


def process_applications(min_score: int = 70) -> list[dict]:
    profile_str = load_file(PROFILE_PATH)
    cv_template = load_file(CV_TEMPLATE_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT rowid AS id, title, company, url, description, fit_score 
        FROM jobs 
        WHERE status = 'EVALUATED' AND fit_score >= ?
    """, (min_score,))

    jobs_to_process = cursor.fetchall()
    newly_generated_jobs = []

    if not jobs_to_process:
        print("Žádné nové pozice ke generování materiálů.")
        conn.close()
        return newly_generated_jobs

    print(f"Generuji materiály pro {len(jobs_to_process)} pozic...")
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    for idx, (job_id, title, company, url, desc, score) in enumerate(jobs_to_process, start=1):
        print(f"\n[{idx}/{len(jobs_to_process)}] Generuji materiály pro: {company} - {title} (Skóre: {score}%)...")

        tailored = None
        attempts = 0
        while attempts < 3:
            try:
                tailored = generate_tailored_texts(profile_str, title, desc)
                break
            except Exception as e:
                attempts += 1
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(f" -> RPM limit dosažen. Čekám 38 sekund (pokus {attempts}/3)...")
                    time.sleep(38)
                else:
                    print(f" -> Chyba při volání API: {e}")
                    break

        if not tailored:
            print(f" -> Přeskakuji {title}, nepodařilo se vygenerovat podklady.")
            continue

        folder_name = sanitize_folder_name(f"{company}_{title}")
        job_dir = APPLICATIONS_DIR / folder_name
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Vyplnění a uložení CV do LaTeXu
            cv_filled = cv_template.replace("{{SUMMARY}}", escape_latex(tailored.cv_summary))
            cv_filled = cv_filled.replace("{{JOBHUNT_HIGHLIGHT}}", escape_latex(tailored.jobhunt_project_bullet))
            cv_filled = cv_filled.replace("{{FLIGHT_HIGHLIGHT}}", escape_latex(tailored.flight_project_bullet))
            cv_filled = cv_filled.replace("{{CYCLISTIC_HIGHLIGHT}}", escape_latex(tailored.cyclistic_project_bullet))

            cv_path = job_dir / "cv.tex"
            with open(cv_path, "w", encoding="utf-8") as f:
                f.write(cv_filled)

            # 2. Uložení průvodního dopisu
            letter_path = job_dir / "pruvodni_dopis.txt"
            letter_content = (
                f"POZICE: {title}\n"
                f"FIRMA: {company}\n"
                f"ODKAZ: {url}\n"
                f"FIT SKÓRE: {score}%\n\n"
                f"--------------------------------------------------\n"
                f"TEXT MOTIVAČNÍHO DOPISU:\n"
                f"--------------------------------------------------\n\n"
                f"{tailored.cover_letter_body}\n"
            )
            with open(letter_path, "w", encoding="utf-8") as f:
                f.write(letter_content)

            # 3. Změna statusu v databázi přes rowid
            cursor.execute("UPDATE jobs SET status = 'GENERATED' WHERE rowid = ?", (job_id,))
            conn.commit()

            print(f" -> Hotovo: {job_dir.relative_to(ROOT_DIR)}")

            newly_generated_jobs.append({
                "title": title,
                "company": company,
                "url": url,
                "score": score,
                "folder": folder_name
            })

        except Exception as e:
            print(f" -> Chyba při zápisu souborů pro {title}: {e}")

        # Prodleva mezi voláními pro dodržení limitu 15 RPM
        time.sleep(4.5)

    conn.close()
    print(f"\nGenerování dokončeno! Úspěšně vytvořeno {len(newly_generated_jobs)} složek.")
    return newly_generated_jobs


if __name__ == "__main__":
    process_applications(min_score=70)