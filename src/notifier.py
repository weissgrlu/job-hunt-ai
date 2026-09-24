import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", SMTP_USER)


def send_email_notification(new_matches: list[dict]):
    """Odešle e-mail se souhrnem nově vygenerovaných žádostí."""
    if not new_matches:
        return

    if not SMTP_USER or not SMTP_PASSWORD:
        print("[Notifier] Chybí SMTP_USER nebo SMTP_PASSWORD v .env – e-mail nelze odeslat.")
        return

    subject = f"🎯 Job-Hunt AI: Nalezeno {len(new_matches)} nových vhodných pozic"

    lines = [f"Ahoj,\n\nrobot našel a zpracoval {len(new_matches)} nových pozic se skóre shody:\n"]
    for job in new_matches:
        lines.append(f"• {job['title']} | {job['company']} (Shoda: {job['score']}%)")
        lines.append(f"  Odkaz: {job['url']}")
        lines.append(f"  Složka: data/applications/{job['folder']}/\n")

    lines.append("Materiály (CV a motivační dopis) jsou připraveny k odeslání.")
    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFICATION_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        print(f"[Notifier] Odesílám e-mail na {NOTIFICATION_EMAIL}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(" -> E-mail úspěšně odeslán!")
    except Exception as e:
        print(f" -> Chyba při odesílání e-mailu: {e}")