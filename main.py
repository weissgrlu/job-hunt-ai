import subprocess
from pathlib import Path
from src.scrapers.jobscz import scrape_jobs, enrich_missing_details
from src.evaluator import process_all_jobs
from src.generator import process_applications
from src.notifier import send_email_notification

ROOT_DIR = Path(__file__).resolve().parent
APPLICATIONS_DIR = ROOT_DIR / "data" / "applications"
TECTONIC_BIN = ROOT_DIR / "tectonic.exe"


def compile_pdfs():
    """Zkompiluje všechna nově vytvořená cv.tex do PDF pomocí lokálního tectonic.exe."""
    if not APPLICATIONS_DIR.exists():
        return

    tex_files = list(APPLICATIONS_DIR.glob("*/cv.tex"))
    if not tex_files:
        return

    cmd_binary = str(TECTONIC_BIN) if TECTONIC_BIN.exists() else "tectonic"

    print("\n--- [FÁZE 4/5] Kompilace CV do PDF (Tectonic) ---")
    for tex_path in tex_files:
        pdf_path = tex_path.with_suffix(".pdf")
        if not pdf_path.exists() or tex_path.stat().st_mtime > pdf_path.stat().st_mtime:
            folder_name = tex_path.parent.name
            print(f"Kompiluji PDF pro: {folder_name}...")
            try:
                subprocess.run(
                    f'"{cmd_binary}" "{tex_path.name}"',
                    cwd=str(tex_path.parent),
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print(f" -> Úspěšně vytvořeno: {pdf_path.name}")
            except subprocess.CalledProcessError as e:
                print(f" -> Chyba při kompilaci {folder_name}: {e.stderr or e}")
            except Exception as e:
                print(f" -> Neočekávaná chyba u {folder_name}: {e}")


def main():
    print("========================================")
    print("   JOB-HUNT-AI: SPOUŠTĚNÍ AUTOMATIZACE  ")
    print("========================================")

    # 1. Scraping z Jobs.cz a doplnění detailů
    print("\n--- [FÁZE 1/5] Scraping Jobs.cz a dotahování detailů ---")
    # Nejdříve projde vyhledávání na Jobs.cz a stáhne nové nabídky
    scrape_jobs()
    # Následně ke všem novým dočte plný text inzerátu
    enrich_missing_details(limit=200)

    # 2. Deterministické AI vyhodnocení
    print("\n--- [FÁZE 2/5] Vyhodnocení inzerátů (Gatekeeper) ---")
    process_all_jobs()

    # 3. Generování materiálů na míru
    print("\n--- [FÁZE 3/5] Generování přihlášek (Score >= 70) ---")
    newly_generated = process_applications(min_score=70)

    # 4. Kompilace do PDF
    compile_pdfs()

    # 5. E-mailová notifikace
    if newly_generated:
        print("\n--- [FÁZE 5/5] Odesílání notifikace ---")
        send_email_notification(newly_generated)
    else:
        print("\n--- [FÁZE 5/5] Žádné nově vygenerované pozice k odeslání. ---")

    print("\n========================================")
    print("   DOKONČENO: Pipeline proběhla úspěšně! ")
    print("========================================")


if __name__ == "__main__":
    main()