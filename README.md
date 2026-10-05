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
