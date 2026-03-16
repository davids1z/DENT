AGENT_SYSTEM_PROMPT = """Ti si DENT AI agent za procjenu osigurateljnih zahtjeva za oštećenja vozila.
Tvoja zadaća je autonomno analizirati sve dostupne dokaze i donijeti odluku o zahtjevu.

Tvoje opcije odluke su:
- AutoApprove: Automatski odobri zahtjev (nizak rizik, svi moduli čisti, trošak ispod praga)
- HumanReview: Proslijedi ljudskom procjenitelju (srednji rizik, neke nedoumice)
- Escalate: Eskaliraj u SIU odjel za posebne istrage (visok rizik prijevare, ozbiljne nekonzistentnosti)

PRAVILA ZA STP (Straight-Through Processing / Automatsko odobrenje):
Za AutoApprove, SVI uvjeti moraju biti ispunjeni:
1. Ukupni trošak ispod {stp_cost_threshold} EUR
2. Nema kritičnih ili ozbiljnih oštećenja
3. Svi forenzički moduli pokazuju nizak rizik (< {stp_max_forensic_risk})
4. Ako je dostupna vremenska provjera, mora potkrijepiti tvrdnju
5. Nema strukturnih problema
6. Sigurnosna ocjena nije kritična

PRAVILA ZA ESKALACIJU:
Bilo koji od sljedećih uvjeta zahtijeva Escalate:
1. Forenzički ukupni rizik >= {escalation_forensic_risk}
2. Bilo koji forenzički modul s rizikom >= {escalation_forensic_risk}
3. Vremenska provjera proturječi tvrdnji (npr. tuča prijavljena, ali ne zabilježena)
4. Više forenzičkih modula s visokim rizikom (>= 0.50)
5. Troškovi iznad {escalation_cost_threshold} EUR s bilo kakvim sumnjivim indikatorima

Za sve ostalo, odluka je HumanReview.

IZLAZNI FORMAT:
Odgovori ISKLJUČIVO u JSON formatu (bez markdown oznaka):
{{
  "outcome": "AutoApprove|HumanReview|Escalate",
  "confidence": 0.0-1.0,
  "reasoning_steps": [
    {{
      "step": 1,
      "category": "naziv kategorije",
      "observation": "što si primijetio",
      "assessment": "tvoja procjena",
      "impact": "utjecaj na odluku"
    }}
  ],
  "weather_assessment": "kratki opis provjere vremena ili null",
  "fraud_indicators": ["lista indikatora prijevare ako postoje"],
  "recommended_actions": ["preporučene radnje"],
  "summary_hr": "Sažetak odluke na hrvatskom (2-3 rečenice)",
  "stp_eligible": true/false,
  "stp_blockers": ["razlozi zašto STP nije moguć, ako postoje"]
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

    # Vehicle info
    v = vehicle_info
    vehicle_parts = []
    if v.get("make"):
        vehicle_parts.append(f"Marka: {v['make']}")
    if v.get("model"):
        vehicle_parts.append(f"Model: {v['model']}")
    if v.get("year"):
        vehicle_parts.append(f"Godina: {v['year']}")
    if v.get("color"):
        vehicle_parts.append(f"Boja: {v['color']}")
    if vehicle_parts:
        sections.append("## VOZILO\n" + "\n".join(vehicle_parts))

    # Capture metadata
    cap = capture_metadata
    cap_parts = []
    if cap.get("source"):
        cap_parts.append(f"Izvor snimke: {cap['source']}")
    if cap.get("latitude") is not None:
        cap_parts.append(f"GPS: {cap['latitude']:.6f}, {cap['longitude']:.6f}")
    if cap_parts:
        sections.append("## METAPODACI SNIMKE\n" + "\n".join(cap_parts))

    # Cost summary
    cost_lines = [f"Raspon troškova: {cost_min:.2f} - {cost_max:.2f} EUR"]
    if gross_total is not None:
        cost_lines.append(f"Bruto ukupno: {gross_total:.2f} EUR")
    sections.append("## TROŠKOVI\n" + "\n".join(cost_lines))

    # Damages
    if damages:
        damage_lines = []
        for i, d in enumerate(damages, 1):
            parts = [
                f"{i}. {d.get('damageType', '?')} na {d.get('carPart', '?')}",
                f"   Ozbiljnost: {d.get('severity', '?')}",
                f"   Opis: {d.get('description', '?')}",
                f"   Pouzdanost: {d.get('confidence', 0):.0%}",
                f"   Trošak: {d.get('estimatedCostMin', 0):.2f} - {d.get('estimatedCostMax', 0):.2f} EUR",
            ]
            if d.get("safetyRating"):
                parts.append(f"   Sigurnost: {d['safetyRating']}")
            if d.get("damageCause"):
                parts.append(f"   Uzrok: {d['damageCause']}")
            if d.get("repairMethod"):
                parts.append(f"   Metoda popravka: {d['repairMethod']}")
            damage_lines.append("\n".join(parts))
        sections.append("## OŠTEĆENJA\n" + "\n".join(damage_lines))
    else:
        sections.append("## OŠTEĆENJA\nNema detektiranih oštećenja.")

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
            forensic_lines.append(f"  ⚠ Greška modula: {error}")

    sections.append("## FORENZIČKA ANALIZA\n" + "\n".join(forensic_lines))

    # Weather verification
    if weather and weather.get("queried"):
        weather_lines = [
            f"Datum: {weather.get('query_date', '?')}",
            f"Lokacija: ({weather.get('latitude', '?')}, {weather.get('longitude', '?')})",
            f"Padaline: {'Da' if weather.get('had_precipitation') else 'Ne'} ({weather.get('precipitation_mm', 0):.1f} mm)",
            f"Tuča: {'Da' if weather.get('had_hail') else 'Ne'}",
            f"Vrijeme: {weather.get('weather_description', '?')} (kod: {weather.get('max_weather_code', '?')})",
        ]
        if weather.get("corroborates_claim") is not None:
            status = "DA" if weather["corroborates_claim"] else "NE"
            weather_lines.append(f"Potkrjepljuje tvrdnju: {status}")
        if weather.get("discrepancy_note"):
            weather_lines.append(f"UPOZORENJE: {weather['discrepancy_note']}")
        if weather.get("error"):
            weather_lines.append(f"Greška API-ja: {weather['error']}")
        sections.append("## VREMENSKA PROVJERA\n" + "\n".join(weather_lines))
    else:
        sections.append("## VREMENSKA PROVJERA\nNije dostupna (nema GPS podataka).")

    return "\n\n".join(sections)
