import json
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

# Cesty k souborům v projektu
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "jobs.db"
PROFILE_PATH = ROOT_DIR / "data" / "profile.json"

# Načtení API klíče
load_dotenv(ROOT_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("Chyba: GEMINI_API_KEY nebyl nalezen v .env!")

client = genai.Client(api_key=API_KEY)


# Schéma výstupu – garantuje, že model vrátí přesná data v JSON formátu
class JobEvaluation(BaseModel):
    fit_score: int = Field(description="Skóre shody od 0 do 100 podle relevantnosti pro profil")
    fit_reasoning: str = Field(description="Stručné shrnutí (2-3 věty): silné shody vs. chybějící požadavky")
    is_match: bool = Field(description="True pokud fit_score >= 65, jinak False")


def load_candidate_profile() -> str:
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def evaluate_job(profile_str: str, job_title: str, job_desc: str) -> JobEvaluation:
    prompt = f"""
Jsi seniorní tech recruiter a kariérní poradce specializovaný na data analytics a business intelligence.

Zhodnoť míru shody mezi profilem kandidáta a nabízenou pracovní pozicí.

PROFIL KANDIDÁTA:
{profile_str}

POZICE: {job_title}
POPIS NABÍDKY:
{job_desc}

Pravidla hodnocení:
1. Seniorní pozice (Senior, Lead, Principal), manažerské IT role s 5+ lety praxe v engineeringu nebo pozice zcela mimo data (čistý backend developer, obchodník) mají mít nízké skóre (0-40).
2. Pozice typu Junior / Medior Data Analyst, BI Analyst, Operations / Data Specialist nebo role kladoucí důraz na SQL, Python, Tableau/BI a silné analytické myšlení mají mít vysoké skóre (65-100).
3. Do zdůvodnění (fit_reasoning) uveď konkrétní shody (např. SQL, Tableau, background) a případné mezery/rizika (např. požadavek na 3+ roky v komerčním bankovnictví).
"""

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": JobEvaluation,
        },
    )

    return JobEvaluation.model_validate_json(response.text)


def process_batch(limit: int = 3):
    profile_str = load_candidate_profile()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Vybereme inzeráty se statusem NEW, které mají stažený plnohodnotný detail
    cursor.execute("""
        SELECT id, title, description 
        FROM jobs 
        WHERE status = 'NEW' AND length(description) > 100
        LIMIT ?
    """, (limit,))

    jobs_to_eval = cursor.fetchall()
    
    if not jobs_to_eval:
        print("Žádné nové inzeráty s detailem k vyhodnocení.")
        conn.close()
        return

    print(f"Začínám vyhodnocovat {len(jobs_to_eval)} inzerátů...")

    for job_id, title, desc in jobs_to_eval:
        print(f"\nAnalyzuji: {title}...")
        try:
            eval_result = evaluate_job(profile_str, title, desc)
            print(f" -> Skóre: {eval_result.fit_score}% (Match: {eval_result.is_match})")
            print(f" -> Důvod: {eval_result.fit_reasoning}")

            # Uložíme výsledek a změníme status z NEW na EVALUATED
            cursor.execute("""
                UPDATE jobs 
                SET fit_score = ?, fit_reasoning = ?, status = 'EVALUATED'
                WHERE id = ?
            """, (eval_result.fit_score, eval_result.fit_reasoning, job_id))
            conn.commit()

        except Exception as e:
            print(f"Chyba při vyhodnocení inzerátu {job_id}: {e}")

    conn.close()
    print("\nHotovo! Všechny inzeráty v této dávce byly uloženy se statusem EVALUATED.")


if __name__ == "__main__":
    process_batch(limit=3)