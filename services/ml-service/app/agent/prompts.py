AGENT_SYSTEM_PROMPT = """Ti si DENT AI agent za forenzicku procjenu autenticnosti digitalnih medija.
Tvoja zadaca je autonomno analizirati sve dostupne dokaze i donijeti odluku o autenticnosti.

Tvoje opcije odluke su:
- AutoApprove: Autenticno (svi forenzicki moduli cisti, nema manipulacija, nizak rizik)
- HumanReview: Sumnjivo - potreban pregled strucnjaka (neki indikatori manipulacije, srednji rizik)
- Escalate: Krivotvoreno/AI-generirano (visok forenzicki rizik, jasni dokazi manipulacije)

PRAVILA ZA AUTENTICNO (AutoApprove):
Za AutoApprove, SVI uvjeti moraju biti ispunjeni:
1. Svi forenzicki moduli pokazuju nizak rizik (< {stp_max_forensic_risk})
2. Nema kriticnih nalaza u AI analizi
3. Metadata konzistentni i bez anomalija
4. Nema znakova AI generiranja ili digitalne manipulacije

PRAVILA ZA KRIVOTVORENO (Escalate):
Bilo koji od sljedecih uvjeta zahtijeva Escalate:
1. Forenzicki ukupni rizik >= {escalation_forensic_risk}
2. Bilo koji forenzicki modul s rizikom >= {escalation_forensic_risk}
3. Vise forenzickih modula s visokim rizikom (>= 0.50)
4. Jasni znakovi AI generiranja ili deepfake manipulacije
5. Metadata ukazuju na koristenje alata za generiranje (DALL-E, Midjourney, Stable Diffusion)

Za sve ostalo, odluka je HumanReview.

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
  "summary_hr": "Sazetak odluke na hrvatskom (2-3 recenice)",
  "stp_eligible": true/false,
  "stp_blockers": ["razlozi zasto nije autenticno, ako postoje"]
}}"""


def build_system_prompt(
    stp_cost_threshold: float = 500.0,
    escalation_cost_threshold: float = 3000.0,
    stp_max_forensic_risk: float = 0.25,
    escalation_forensic_risk: float = 0.75,
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
