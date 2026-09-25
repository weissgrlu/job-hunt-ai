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
        description="Profesní shrnutí (2-3 věty) do záhlaví CV, psané česky, zdůrazňující analytické schopnosti a přesah kandidáta relevantní pro tuto pozici."
    )
    jobhunt_project_bullet: str = Field(
        description="Jedna konkrétní věta v češtině doplňující projekt JobHunt AI. Vyzdvihni automatizaci datové pipeline, integraci LLM API, scraping nebo architekturu zpracování dat s vazbou na danou roli."
    )
    flight_project_bullet: str = Field(
        description="Jedna konkrétní věta v češtině doplňující letecký projekt (The Hidden Cost of Weather). Vyzdvihni práci s Pythonem, parsování dat, časové řady nebo vizualizace v Tableau s vazbou na danou roli."
    )
    cyclistic_project_bullet: str = Field(
        description="Jedna konkrétní věta v češtině doplňující projekt Cyclistic Bike-Share. Vyzdvihni pokročilé SQL v BigQuery nad velkým objemem dat, EDA, kohorty nebo byznys segmentaci s vazbou na danou roli."
    )
    cover_letter_body: str = Field(
        description="Strukturovaný text motivačního dopisu (3 odstavce: úvod a motivace, konkrétní přínos a projekty/stack, závěr a výzva k setkání)."
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
Jsi zkušený kariérní poradce. Vytvoř na míru šité podklady pro kandidáta hlásícího se na tuto pozici.

PROFIL KANDIDÁTA:
{profile_str}

POZICE: {job_title}
POPIS POZICE:
{job_desc}

ÚKOL:
1. `cv_summary`: Napiš úderné shrnutí profilu (2-3 věty v češtině). Vyzdvihni exaktní analytické myšlení (MFF UK), pokročilé SQL/Python/BI a schopnost interpretovat data pro byznys.
2. `jobhunt_project_bullet`: Napiš jednu konkrétní větu v češtině přímo navazující na projekt JobHunt AI. Zdůrazni robustní end-to-end automatizaci procesů, orchestraci databáze (SQLite) a propojení AI s reálnou aplikací s ohledem na požadavky v inzerátu.
3. `flight_project_bullet`: Napiš jednu konkrétní větu v češtině přímo navazující na letecký projekt (audit zpoždění letů, METAR počasí). Zdůrazni práci v Pythonu, čištění nestrukturovaných dat, časové řady nebo reporting relevantní pro tuto pozici.
4. `cyclistic_project_bullet`: Napiš jednu konkrétní větu v češtině přímo navazující na projekt Cyclistic Bike-Share. Zdůrazni práci v Google BigQuery (SQL) nad 5,9M řádky a segmentaci pro byznys rozhodování relevantní pro tuto pozici.
5. `cover_letter_body`: Napiš profesionální, věcný a sebevědomý motivační dopis (cca 3 odstavce v češtině). Žádné prázdné fráze. Zaměř se na okamžitou přidanou hodnotu.
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
            # 1. Vyplnění a uložení CV do LaTeXu se všemi třemi projekty
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

        # Bezpečná prodleva mezi voláními pro dodržení limitu 15 RPM
        time.sleep(4.5)

    conn.close()
    print(f"\nGenerování dokončeno! Úspěšně vytvořeno {len(newly_generated_jobs)} složek.")
    return newly_generated_jobs


if __name__ == "__main__":
    process_applications(min_score=70)