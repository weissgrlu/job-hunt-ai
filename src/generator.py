import os
import re
import sqlite3
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
    selected_project_bullet: str = Field(
        description="Jedna konkrétní věta/odrážka vyzdvihující kandidátův projekt (např. analýza zpoždění letů nebo Cyclistic) a jeho relevanci k této roli."
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
2. `selected_project_bullet`: Vyber nejrelevantnější aspekt z portfolia a zformuluj jednu větu, jak tento projekt demonstruje schopnosti nutné pro tuto roli.
3. `cover_letter_body`: Napiš profesionální, věcný a sebevědomý motivační dopis (cca 3 odstavce v češtině). Žádné prázdné fráze. Zaměř se na okamžitou přidanou hodnotu.
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
    """
    Vybere inzeráty s fit_score >= min_score a stavem 'EVALUATED',
    vygeneruje pro ně CV i dopis a VRÁTÍ seznam vytvořených pozic pro notifikaci.
    """
    profile_str = load_file(PROFILE_PATH)
    cv_template = load_file(CV_TEMPLATE_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, company, url, description, fit_score 
        FROM jobs 
        WHERE status = 'EVALUATED' AND fit_score >= ?
    """, (min_score,))

    jobs_to_process = cursor.fetchall()

    # Zde si budeme ukládat pozice, které úspěšně vytvoříme
    newly_generated_jobs = []

    if not jobs_to_process:
        print("Žádné nové pozice ke generování materiálů.")
        conn.close()
        return newly_generated_jobs

    print(f"Generuji materiály pro {len(jobs_to_process)} pozic...")
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    for job_id, title, company, url, desc, score in jobs_to_process:
        folder_name = sanitize_folder_name(f"{company}_{title}")
        job_dir = APPLICATIONS_DIR / folder_name
        job_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nGeneruji materiály pro: {company} - {title} (Skóre: {score}%)...")

        try:
            tailored = generate_tailored_texts(profile_str, title, desc)

            # 1. Vyplnění a uložení CV do LaTeXu
            cv_filled = cv_template.replace("{{SUMMARY}}", escape_latex(tailored.cv_summary))
            cv_filled = cv_filled.replace("{{PROJECT_HIGHLIGHT}}", escape_latex(tailored.selected_project_bullet))

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

            # 3. Změna statusu v databázi
            cursor.execute("UPDATE jobs SET status = 'GENERATED' WHERE id = ?", (job_id,))
            conn.commit()

            print(f" -> Soubory vytvořeny v: {job_dir.relative_to(ROOT_DIR)}")

            # 4. Přidáme pozici do seznamu pro e-mailovou notifikaci
            newly_generated_jobs.append({
                "title": title,
                "company": company,
                "url": url,
                "score": score,
                "folder": folder_name
            })

        except Exception as e:
            print(f" -> Chyba při generování pro {title}: {e}")

    conn.close()
    print(f"\nGenerování dokončeno! Připraveno {len(newly_generated_jobs)} složek.")
    
    # Vracíme seznam pozic pro main.py
    return newly_generated_jobs


if __name__ == "__main__":
    process_applications(min_score=70)