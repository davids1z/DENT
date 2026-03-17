AGENT_SYSTEM_PROMPT = """Ti si DENT AI agent za forenzicku procjenu autenticnosti digitalnih medija.
Tvoja zadaca je analizirati sve dostupne dokaze i OBJASNITI forenzicke nalaze.

VAZNO: Tvoja odluka (outcome) je SAVJETODAVNA. Konacni verdikt donosi deterministicki
Decision Engine na temelju forenzickih fusion rezultata. Tvoj zadatak je OBJASNITI
i OPISATI nalaze na razumljiv nacin, ne donositi konacnu presudu.

Tvoje preporuke odluke su:
- AutoApprove: Autenticno (svi forenzicki moduli cisti, nema manipulacija, nizak rizik)
- HumanReview: Sumnjivo - potreban pregled strucnjaka (neki indikatori manipulacije, srednji rizik)
- Escalate: Krivotvoreno/AI-generirano (visok forenzicki rizik, jasni dokazi manipulacije)

=== KRITICNO PRAVILO: FORENZICKI MODULI SU IZVOR ISTINE ===
Forenzicki moduli (CNN detekcija, spektralna analiza, ELA, metadata) koriste statisticke
i ML metode koje su POUZDANIJE od vizualne AI analize. Forenzicki fusion score je
DETERMINISTICKI i NEPOBITNI — tvoj posao je objasniti ZASTO su moduli dali takav rezultat.
- Ako forenzicki moduli pokazuju visok rizik, MORAS to odraziti u objasnjenju
- NE SMIJES umanjivati ili relativizirati visoke forenzicke rezultate
- CNN modul (deep_modification_detection), AI detekcija (ai_generation_detection) i
  spektralna forenzika (spectral_forensics) su posebno pouzdani detektori

TVOJ FOKUS:
1. Objasni STO su forenzicki moduli detektirali — na razumljiv, ne-tehnicki nacin
2. Povezi forenzicke nalaze medjusobno — npr. "AI detektor i spektralna analiza se slazu"
3. Navedi specificne fraud indikatore ako postoje
4. Preporuci sljedece korake (ljudski pregled, dodatne provjere, itd.)
5. Napravi sazetak na hrvatskom koji je razumljiv krajnjem korisniku

IZLAZNI FORMAT:
Odgovori ISKLJUCIVO u JSON formatu (bez markdown oznaka):
{{
  "outcome": "AutoApprove|HumanReview|Escalate",
  "confidence": 0.0-1.0,
  "reasoning_steps": [
    {{
      "step": 1,
      "category": "naziv kategorije",
      "observation": "sto si primijetio",
      "assessment": "tvoja procjena",
      "impact": "utjecaj na odluku"
    }}
  ],
  "weather_assessment": null,
  "fraud_indicators": ["lista indikatora krivotvorenja ako postoje"],
  "recommended_actions": ["preporucene radnje"],
  "summary_hr": "Sazetak nalaza na hrvatskom (2-3 recenice). Objasni sto forenzicki moduli kazu i sto to znaci.",
  "stp_eligible": true/false,
  "stp_blockers": ["razlozi zasto nije autenticno, ako postoje"]
}}"""


def build_system_prompt(
    stp_cost_threshold: float = 500.0,
    escalation_cost_threshold: float = 3000.0,
    stp_max_forensic_risk: float = 0.25,
    escalation_forensic_risk: float = 0.60,
) -> str:
    return AGENT_SYSTEM_PROMPT.format(
        stp_cost_threshold=stp_cost_threshold,
        escalation_cost_threshold=escalation_cost_threshold,
        stp_max_forensic_risk=stp_max_forensic_risk,
        escalation_forensic_risk=escalation_forensic_risk,
    )


def build_evidence_prompt(
    damages: list[dict],
    forensic_modules: list[dict],
    overall_forensic_risk: float,
    overall_forensic_level: str,
    weather: dict | None,
    cost_min: float,
    cost_max: float,
    gross_total: float | None,
    vehicle_info: dict,
    capture_metadata: dict,
) -> str:
    sections: list[str] = []

    # Capture metadata
    cap = capture_metadata
    cap_parts = []
    if cap.get("source"):
        cap_parts.append(f"Izvor snimke: {cap['source']}")
    if cap.get("latitude") is not None:
        cap_parts.append(f"GPS: {cap['latitude']:.6f}, {cap['longitude']:.6f}")
    if cap_parts:
        sections.append("## METAPODACI SNIMKE\n" + "\n".join(cap_parts))

    # AI analysis findings
    if damages:
        finding_lines = []
        for i, d in enumerate(damages, 1):
            parts = [
                f"{i}. Kategorija: {d.get('damageCause', 'Nepoznato')}",
                f"   Razina sumnje: {d.get('severity', '?')}",
                f"   Opis: {d.get('description', '?')}",
                f"   Pouzdanost: {d.get('confidence', 0):.0%}",
            ]
            if d.get("safetyRating"):
                parts.append(f"   Verdikt: {d['safetyRating']}")
            finding_lines.append("\n".join(parts))
        sections.append("## NALAZI AI ANALIZE\n" + "\n".join(finding_lines))
    else:
        sections.append("## NALAZI AI ANALIZE\nNema detektiranih anomalija - slika izgleda autenticna.")

    # Forensic analysis
    forensic_lines = [
        f"Ukupni rizik: {overall_forensic_risk:.2f} ({overall_forensic_level})"
    ]
    for m in forensic_modules:
        name = m.get("moduleLabel") or m.get("moduleName", "?")
        score = m.get("riskScore", 0)
        level = m.get("riskLevel", "?")
        forensic_lines.append(f"\n### {name} — Rizik: {score:.2f} ({level})")

        findings = m.get("findings", [])
        if findings:
            for f in findings:
                forensic_lines.append(
                    f"  - [{f.get('code', '?')}] {f.get('title', '?')}: "
                    f"{f.get('description', '')} "
                    f"(rizik: {f.get('riskScore', 0):.2f}, pouzdanost: {f.get('confidence', 0):.0%})"
                )

        error = m.get("error")
        if error:
            forensic_lines.append(f"  ⚠ Greska modula: {error}")

    sections.append("## FORENZICKA ANALIZA\n" + "\n".join(forensic_lines))

    return "\n\n".join(sections)
