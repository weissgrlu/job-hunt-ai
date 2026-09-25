import json
import os
import sqlite3
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "jobs.db"
PROFILE_PATH = ROOT_DIR / "data" / "profile.json"

load_dotenv(ROOT_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("Chyba: GEMINI_API_KEY nebyl nalezen v .env!")

client = genai.Client(api_key=API_KEY)


class HardFactsExtraction(BaseModel):
    is_senior_or_lead: bool = Field(
        description="True if the role is Senior, Lead, Principal, Architect, or Team Lead (in Czech or English)."
    )
    is_junior_or_graduate: bool = Field(
        description="True if the job explicitly mentions 'junior', 'graduate', 'absolvent', 'entry level', or 'trainee'."
    )
    has_concrete_tech_requirements: bool = Field(
        description="True if the text contains explicit technical skills, data tools, or methodologies required (e.g., SQL, Excel, Python, Power BI, Tableau, ETL). False if the text is only general company marketing, intro, culture, or vague generic text without technical requirements."
    )
    relevant_data_tools_found: list[str] = Field(
        description="List of relevant data tools and technologies explicitly mentioned in the posting (e.g. ['SQL', 'Power BI', 'Excel', 'Python', 'Tableau', 'BigQuery'])."
    )
    required_years_experience: int = Field(
        description="Minimum years of commercial experience strictly required (number). E.g. '3+ years' -> 3. If no years specified, or only 'advantage/nice to have', return 0."
    )
    missing_critical_tech: list[str] = Field(
        description="Mandatory technologies required that the candidate DOES NOT know (Candidate knows: SQL, BigQuery, Tableau, Power BI, Python Pandas/NumPy, Git, Advanced Excel). E.g. Spark, C#, Java, AWS DevOps, SAP ABAP."
    )
    evaluation_summary: str = Field(
        description="Stručné shrnutí česky (1-2 věty) popisující šanci kandidáta vzhledem k požadavkům na praxi a tech stack."
    )


def load_candidate_profile() -> str:
    if PROFILE_PATH.exists():
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def ensure_evaluator_columns():
    """Zajistí, že tabulka jobs obsahuje sloupce pro evaluaci."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(jobs)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        if "status" not in existing_cols:
            cursor.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'NEW'")
        if "fit_score" not in existing_cols:
            cursor.execute("ALTER TABLE jobs ADD COLUMN fit_score INTEGER DEFAULT 0")
        if "fit_reasoning" not in existing_cols:
            cursor.execute("ALTER TABLE jobs ADD COLUMN fit_reasoning TEXT DEFAULT ''")
        conn.commit()


def clean_database_duplicates():
    """Automaticky pročistí duplicity podle názvu a firmy pomocí rowid."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM jobs 
        WHERE rowid NOT IN (
            SELECT min_rowid FROM (
                SELECT rowid as min_rowid, 
                       ROW_NUMBER() OVER (
                           PARTITION BY lower(trim(company)), lower(trim(title)) 
                           ORDER BY length(ifnull(description, '')) DESC, rowid DESC
                       ) as rn 
                FROM jobs
            ) WHERE rn = 1
        )
    """)
    conn.commit()
    conn.close()


def extract_and_evaluate(profile_str: str, job_title: str, job_desc: str) -> tuple[int, str, bool]:
    prompt = f"""
You are a strict, no-nonsense tech recruiter auditing job postings (in Czech or English) for a specific candidate.

CANDIDATE:
- Education: Charles University (MFF UK - Mathematics/Physics & Statistics, graduated with honors)
- Stack: SQL (Google BigQuery, PostgreSQL), Python (Pandas, NumPy, EDA, Regex), Tableau, Power BI, Advanced Excel, Git
- Background: Vice Principal (operations & data management), high school math/physics teacher.
- Commercial data warehouse / corporate BI experience: 0 formal corporate years (has verified portfolio projects and management data experience, but NO long corporate tenure).

JOB TITLE: {job_title}
JOB DESCRIPTION (may be in Czech or English):
{job_desc}

EXTRACTION RULES:
1. `has_concrete_tech_requirements`: Return FALSE if the job text has no specific tools or technical expectations (e.g. only company intro, office perks, generic form text).
2. `relevant_data_tools_found`: Extract all data tools explicitly requested (e.g., SQL, Power BI, Tableau, Python, Excel).
3. `required_years_experience`: Extract integer. If text says "at least 3 years of experience" / "min. 3 roky praxe", return 3. If "experience is an advantage" / "praxe výhodou" without strict minimum, return 0.
4. `is_senior_or_lead`: True if title/text targets senior level, lead, or mentoring others.
5. `missing_critical_tech`: List only core required technologies candidate does not have (e.g., C++, Scala, Java, Spark, Cloud Architecture).
6. `evaluation_summary`: Write 1-2 concise sentences in Czech explaining the decision based on concrete requirements.
"""

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": HardFactsExtraction,
        },
    )

    facts = HardFactsExtraction.model_validate_json(response.text)

    # Přísná penalizace za chybějící požadavky
    if not facts.has_concrete_tech_requirements:
        score = 25
        reason = f"{facts.evaluation_summary} [Chybí konkrétní technické požadavky na stack/pozici.]"
        return score, reason, False

    # Deterministický výpočet skóre
    score = 75
    reasons = []

    # Bonus za průnik se stackem kandidáta
    stack_matches = [t for t in facts.relevant_data_tools_found if any(k in t.lower() for k in ["sql", "power bi", "tableau", "python", "excel", "bigquery"])]
    if stack_matches:
        score += min(15, len(stack_matches) * 5)
        reasons.append(f"Shoda ve stacku: {', '.join(stack_matches)}")

    # Penalizace za praxi
    if facts.required_years_experience >= 3:
        score -= 50
        reasons.append(f"Vyžaduje {facts.required_years_experience}+ let praxe.")
    elif facts.required_years_experience >= 2:
        score -= 30
        reasons.append("Vyžaduje min. 2 roky komerční praxe.")
    elif facts.required_years_experience == 1:
        score -= 10
        reasons.append("Požadován 1 rok praxe.")

    # Penalizace za senioritu
    if facts.is_senior_or_lead:
        score -= 40
        reasons.append("Seniorní/vedoucí role.")

    # Bonus pro juniory
    if facts.is_junior_or_graduate:
        score += 10
        reasons.append("Vhodné pro juniory/absolventy.")

    # Penalizace za chybějící technologie
    if len(facts.missing_critical_tech) >= 2:
        score -= 30
        reasons.append(f"Chybí: {', '.join(facts.missing_critical_tech)}.")
    elif len(facts.missing_critical_tech) == 1:
        score -= 15
        reasons.append(f"Chybí: {facts.missing_critical_tech[0]}.")

    score = max(5, min(95, score))
    is_match = (score >= 70) and (facts.required_years_experience < 2) and (not facts.is_senior_or_lead)

    full_reason = f"{facts.evaluation_summary} [{' | '.join(reasons)}]" if reasons else facts.evaluation_summary
    return score, full_reason, is_match


def process_all_jobs():
    ensure_evaluator_columns()

    print("Čistím případné duplicity v databázi...")
    clean_database_duplicates()

    profile_str = load_candidate_profile()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Zpracujeme inzeráty, které mají stažený popis a ještě nebyly vyhodnoceny
    cursor.execute("""
        SELECT url, title, description 
        FROM jobs 
        WHERE (status IS NULL OR status = 'NEW') AND length(ifnull(description, '')) > 100
    """)
    jobs_to_eval = cursor.fetchall()

    if not jobs_to_eval:
        print("Žádné nové inzeráty k vyhodnocení.")
        conn.close()
        return

    print(f"Vyhodnocuji {len(jobs_to_eval)} nových inzerátů...")
    matches_count = 0

    for idx, (url, title, desc) in enumerate(jobs_to_eval, start=1):
        print(f"\n[{idx}/{len(jobs_to_eval)}] Analyzuji: {title[:60]}...")

        success = False
        attempts = 0
        while not success and attempts < 3:
            try:
                score, reasoning, is_match = extract_and_evaluate(profile_str, title, desc)
                success = True
            except Exception as e:
                attempts += 1
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(f" -> RPM limit. Čekám 20s (pokus {attempts}/3)...")
                    time.sleep(20)
                else:
                    print(f" -> Chyba: {e}")
                    break

        if not success:
            continue

        print(f" -> Skóre: {score}% | Match: {is_match}")
        print(f" -> Důvod: {reasoning}")

        if is_match:
            matches_count += 1

        cursor.execute("""
            UPDATE jobs 
            SET fit_score = ?, fit_reasoning = ?, status = 'EVALUATED'
            WHERE url = ?
        """, (score, reasoning, url))
        conn.commit()

        time.sleep(4.3)

    conn.close()
    print(f"\nDokončeno! Přibylo {matches_count} vyhovujících pozic.")


if __name__ == "__main__":
    process_all_jobs()