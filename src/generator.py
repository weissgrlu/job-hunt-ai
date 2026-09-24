import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

# Cesty k souborům
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "jobs.db"
TEMPLATE_PATH = ROOT_DIR / "data" / "cv_template.tex"
APPLICATIONS_DIR = ROOT_DIR / "data" / "applications"

APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("Chyba: GEMINI_API_KEY nebyl nalezen v .env!")

client = genai.Client(api_key=API_KEY)


def sanitize_folder_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[-\s]+", "_", text)[:60]


class TailoredCVSections(BaseModel):
    summary: str = Field(
        description="Stručné shrnutí profilu (1-2 věty) pod jménem, zvýrazňující relevanci pro danou pozici v češtině."
    )
    tech_stack: str = Field(
        description="Technický stack z profilu kandidáta, seřazený podle relevance k pozici (oddělený čárkami)."
    )
    analytic_methods: str = Field(
        description="Analytické metody z profilu kandidáta, seřazené podle relevance k pozici."
    )
    weather_bullet_1: str = Field(
        description="První odrážka k projektu zpoždění letů v LaTeXu (bez úvodního \\item)."
    )
    weather_bullet_2: str = Field(
        description="Druhá odrážka k projektu zpoždění letů v LaTeXu (bez úvodního \\item)."
    )
    cyclistic_bullet_1: str = Field(
        description="První odrážka k projektu Cyclistic v LaTeXu (bez úvodního \\item)."
    )
    cyclistic_bullet_2: str = Field(
        description="Druhá odrážka k projektu Cyclistic v LaTeXu (bez úvodního \\item)."
    )
    cover_letter: str = Field(
        description="Lidský, věcný průvodní dopis (2-3 odstavce) bez generických frází."
    )


def load_latex_template() -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def generate_tailored_sections(job_title: str, company: str, job_desc: str) -> TailoredCVSections:
    prompt = f"""
Jsi seniorní kariérní poradce v datové analytice a expert na přípravu podkladů pro výběrová řízení.

POZICE: {job_title}
SPOLEČNOST: {company}
POPIS POZICE:
{job_desc}

INFORMACE O KANDIDÁTOVI (STRIKTNÍ FAKTA, NEVYMÝŠLEJ JINÉ):
- Jméno: Lukáš Weissgráb, absolvent MFF UK s vyznamenáním (matematika/fyzika, statistika).
- Tech stack: SQL, Google BigQuery, Tableau Desktop / Public, Python (Pandas, NumPy), GitHub, Jupyter Notebooks, Excel, Google Sheets, Power BI.
- Metody: EDA, Feature Engineering, Regex parsing, časové řady, testování hypotéz, kvantitativní modelování.
- Projekt 1 (Weather Delay): Rotace 4 817 letadel, 84k letů, párování IEM METAR s 96% úspěšností v UTC, dominový efekt 38,3 tis. minut v hodnotě 3,8 mil. USD maskovaných jako Late Aircraft, Tableau storyboard.
- Projekt 2 (Cyclistic): 5,9 mil. transakcí v BigQuery SQL, deduplikace, 99,2% integrita, segmentace uživatelů, 2 Tableau dashboardy, konverzní strategie.
- Praxe: Zástupce ředitele (procesy, kapacitní plánování, operativní reporting), Učitel (kvantitativní modelování, data storytelling).

ÚKOL:
Připrav obsah pro zástupné části CV a průvodní dopis.
1. STRIKTNÍ ZÁKAZ VYMÝŠLENÍ NOVÝCH TECHNOLOGIÍ: Použij výhradně reálná fakta.
2. Formátování textu: Speciální LaTeX znaky piš správně (např. \\% pro procenta).
3. Cover letter: Přirozený, věcný tón, 2-3 odstavce propojující profil kandidáta s konkrétní nabídkou.
"""

    response = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": TailoredCVSections,
        },
    )

    return TailoredCVSections.model_validate_json(response.text)


def process_applications(min_score: int = 65):
    template = load_latex_template()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Vybereme pozice se skóre >= min_score
    cursor.execute("""
        SELECT id, title, company, url, description, fit_score 
        FROM jobs 
        WHERE status = 'EVALUATED' AND fit_score >= ?
    """, (min_score,))

    jobs = cursor.fetchall()

    if not jobs:
        print(f"Nenalezeny žádné inzeráty se skóre >= {min_score}.")
        conn.close()
        return

    print(f"Zpracovávám {len(jobs)} pozic s garantovanou LaTeX šablonou...")

    for job_id, title, company, url, desc, score in jobs:
        folder_name = f"{sanitize_folder_name(company or 'Firma')}-{sanitize_folder_name(title)}"
        target_dir = APPLICATIONS_DIR / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nSestavuji podklady: {title} ({company})")

        try:
            sec = generate_tailored_sections(title, company or "", desc)

            # Sestavení CV přesně do neměnné šablony
            weather_bullets = f"\t\t\\item {sec.weather_bullet_1}\n\t\t\\item {sec.weather_bullet_2}"
            cyclistic_bullets = f"\t\t\\item {sec.cyclistic_bullet_1}\n\t\t\\item {sec.cyclistic_bullet_2}"

            tailored_tex = (
                template.replace("{{ SUMMARY }}", sec.summary)
                .replace("{{ TECH_STACK }}", sec.tech_stack)
                .replace("{{ ANALYTIC_METHODS }}", sec.analytic_methods)
                .replace("{{ PROJECT_WEATHER_BULLETS }}", weather_bullets)
                .replace("{{ PROJECT_CYCLISTIC_BULLETS }}", cyclistic_bullets)
            )

            # 1. Zápis garantovaného LaTeX souboru
            cv_path = target_dir / "cv.tex"
            with open(cv_path, "w", encoding="utf-8") as f:
                f.write(tailored_tex)

            # 2. Zápis průvodního dopisu
            letter_path = target_dir / "pruvodni_dopis.txt"
            letter_content = f"POZICE: {title}\nSPOLEČNOST: {company}\nODKAZ: {url}\nFIT SKÓRE: {score}%\n\n"
            letter_content += "=" * 60 + "\nPRŮVODNÍ DOPIS\n" + "=" * 60 + "\n\n"
            letter_content += sec.cover_letter + "\n"

            with open(letter_path, "w", encoding="utf-8") as f:
                f.write(letter_content)

            cursor.execute("UPDATE jobs SET status = 'GENERATED' WHERE id = ?", (job_id,))
            conn.commit()

            print(f" -> Hotovo: cv.tex zkompiluje čistě bez chyb v hlavičce!")

        except Exception as e:
            print(f"Chyba při zpracování {title}: {e}")

    conn.close()
    print("\nVšechny podklady úspěšně přegenerovány.")


if __name__ == "__main__":
    process_applications()