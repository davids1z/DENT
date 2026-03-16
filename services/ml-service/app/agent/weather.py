import logging
from datetime import datetime

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

WEATHER_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "Vedro",
    1: "Pretežno vedro",
    2: "Djelomično oblačno",
    3: "Oblačno",
    45: "Magla",
    48: "Magla s mrazom",
    51: "Slaba sitna kiša",
    53: "Umjerena sitna kiša",
    55: "Jaka sitna kiša",
    61: "Slaba kiša",
    63: "Umjerena kiša",
    65: "Jaka kiša",
    66: "Slaba ledena kiša",
    67: "Jaka ledena kiša",
    71: "Slab snijeg",
    73: "Umjeren snijeg",
    75: "Jak snijeg",
    77: "Zrnca snijega",
    80: "Slabi pljuskovi",
    81: "Umjereni pljuskovi",
    82: "Jaki pljuskovi",
    85: "Slab snježni pljusak",
    86: "Jak snježni pljusak",
    95: "Grmljavina",
    96: "Grmljavina s laganom tučom",
    99: "Grmljavina s jakom tučom",
}

HAIL_CODES = {96, 99}
STORM_CODES = {95, 96, 99}
HEAVY_PRECIP_CODES = {65, 67, 75, 82, 86, 95, 96, 99}

HAIL_KEYWORDS = ["tuča", "tuca", "hail", "grad"]
STORM_KEYWORDS = ["oluja", "storm", "nevrijeme", "grmljavina"]


class WeatherVerification(BaseModel):
    queried: bool
    latitude: float | None = None
    longitude: float | None = None
    query_date: str | None = None
    had_hail: bool = False
    had_precipitation: bool = False
    precipitation_mm: float = 0.0
    max_weather_code: int | None = None
    weather_description: str | None = None
    corroborates_claim: bool | None = None
    discrepancy_note: str | None = None
    error: str | None = None


async def verify_weather(
    latitude: float | None,
    longitude: float | None,
    capture_timestamp: str | None,
    damage_causes: list[str] | None = None,
) -> WeatherVerification:
    """Query Open-Meteo historical weather for GPS location and date."""

    if latitude is None or longitude is None:
        return WeatherVerification(queried=False)

    # Parse date from capture timestamp
    try:
        if capture_timestamp:
            dt = datetime.fromisoformat(capture_timestamp.replace("Z", "+00:00"))
        else:
            dt = datetime.utcnow()
        query_date = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return WeatherVerification(queried=False, error="Invalid capture timestamp")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    "latitude": round(latitude, 4),
                    "longitude": round(longitude, 4),
                    "start_date": query_date,
                    "end_date": query_date,
                    "hourly": "precipitation,weathercode",
                    "timezone": "auto",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Weather API call failed: %s", e)
        return WeatherVerification(
            queried=True,
            latitude=latitude,
            longitude=longitude,
            query_date=query_date,
            error=str(e),
        )

    # Parse hourly data
    hourly = data.get("hourly", {})
    precip_values = hourly.get("precipitation", [])
    weather_codes = hourly.get("weathercode", [])

    total_precip = sum(v for v in precip_values if v is not None)
    had_precipitation = total_precip > 0.1

    valid_codes = [c for c in weather_codes if c is not None]
    max_code = max(valid_codes) if valid_codes else None
    had_hail = any(c in HAIL_CODES for c in valid_codes)

    weather_desc = WEATHER_CODE_DESCRIPTIONS.get(max_code, "Nepoznato") if max_code is not None else None

    # Evaluate claim corroboration
    corroborates = None
    discrepancy = None
    causes_lower = [c.lower() for c in (damage_causes or [])]

    claims_hail = any(kw in cause for cause in causes_lower for kw in HAIL_KEYWORDS)
    claims_storm = any(kw in cause for cause in causes_lower for kw in STORM_KEYWORDS)

    if claims_hail:
        if had_hail:
            corroborates = True
        else:
            corroborates = False
            discrepancy = (
                f"Prijavljeno oštećenje od tuče, ali meteorološki podaci za "
                f"{query_date} na lokaciji ({latitude:.4f}, {longitude:.4f}) "
                f"ne bilježe tuču. Maksimalni vremenski kod: {max_code} ({weather_desc})."
            )
    elif claims_storm:
        if any(c in STORM_CODES for c in valid_codes):
            corroborates = True
        else:
            corroborates = False
            discrepancy = (
                f"Prijavljeno oštećenje od oluje, ali meteorološki podaci za "
                f"{query_date} ne bilježe grmljavinu ili oluju na toj lokaciji."
            )

    return WeatherVerification(
        queried=True,
        latitude=latitude,
        longitude=longitude,
        query_date=query_date,
        had_hail=had_hail,
        had_precipitation=had_precipitation,
        precipitation_mm=round(total_precip, 1),
        max_weather_code=max_code,
        weather_description=weather_desc,
        corroborates_claim=corroborates,
        discrepancy_note=discrepancy,
    )
