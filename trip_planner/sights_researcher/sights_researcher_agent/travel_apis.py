"""Live travel-data tools: flights, currency, weather, places, and
driving-eligibility reference info.

Each tool degrades gracefully — returning {"available": False, "reason": ...}
instead of raising — when its API key isn't set, so the agent can still run
the demo end-to-end and just skip that data source. Hotel and car pricing
aren't live-integrated (Duffel Stays/Cars need account access this project
doesn't have yet) — the agent estimates those from load_web_page research
and its own knowledge instead.
"""

import asyncio
import concurrent.futures

import requests
from google.adk.tools import FunctionTool

from sights_researcher_agent import config

_TIMEOUT = 15
_DUFFEL_BASE_URL = "https://api.duffel.com"
_DUFFEL_HEADERS_BASE = {"Duffel-Version": "v2", "Content-Type": "application/json", "Accept": "application/json"}


def _duffel_headers() -> dict | None:
    token = config.duffel_api_key()
    if not token:
        return None
    return {**_DUFFEL_HEADERS_BASE, "Authorization": f"Bearer {token}"}


# ---- Duffel: flights -------------------------------------------------------

def _search_flights(origin: str, destination: str, departure_date: str, adults: int) -> dict:
    headers = _duffel_headers()
    if not headers:
        return {"available": False, "reason": "Duffel API key not configured."}

    resp = requests.post(
        f"{_DUFFEL_BASE_URL}/air/offer_requests?return_offers=true",
        headers=headers,
        json={
            "data": {
                "slices": [{"origin": origin, "destination": destination, "departure_date": departure_date}],
                "passengers": [{"type": "adult"} for _ in range(adults)],
                "cabin_class": "economy",
            }
        },
        timeout=_TIMEOUT,
    )
    if not resp.ok:
        return {"available": False, "reason": resp.text[:300]}

    offers = [
        {
            "airline": offer["owner"]["name"],
            "total_price": f"{offer['total_amount']} {offer['total_currency']}",
            "stops": len(offer["slices"][0]["segments"]) - 1,
            "duration": offer["slices"][0].get("duration"),
        }
        for offer in resp.json().get("data", {}).get("offers", [])[:5]
    ]
    return {"available": True, "offers": offers}


# ---- Currency exchange (open.er-api.com, no key required) -----------------

def _exchange_rate(base_currency: str, target_currency: str, amount: float) -> dict:
    resp = requests.get(f"https://open.er-api.com/v6/latest/{base_currency.upper()}", timeout=_TIMEOUT)
    if not resp.ok:
        return {"available": False, "reason": resp.text[:300]}
    rates = resp.json().get("rates", {})
    rate = rates.get(target_currency.upper())
    if rate is None:
        return {"available": False, "reason": f"Unknown currency code: {target_currency}"}
    return {"available": True, "rate": rate, "converted_amount": round(amount * rate, 2)}


# ---- Weather (OpenWeatherMap) ----------------------------------------------

def _weather_forecast(city: str) -> dict:
    api_key = config.openweather_api_key()
    if not api_key:
        return {"available": False, "reason": "OpenWeatherMap API key not configured."}

    def _get(endpoint: str):
        return requests.get(
            f"https://api.openweathermap.org/data/2.5/{endpoint}",
            params={"q": city, "appid": api_key, "units": "metric"},
            timeout=_TIMEOUT,
        )

    # Independent requests — run concurrently instead of paying both
    # latencies back-to-back.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        current_future = pool.submit(_get, "weather")
        forecast_future = pool.submit(_get, "forecast")
        current = current_future.result()
        forecast = forecast_future.result()

    if not current.ok:
        return {"available": False, "reason": current.text[:300]}
    current_body = current.json()

    daily = []
    if forecast.ok:
        # One entry per ~24h (every 8th 3-hour slot) for the next few days.
        daily = [
            {"time": e["dt_txt"], "temp_c": e["main"]["temp"], "conditions": e["weather"][0]["description"]}
            for e in forecast.json().get("list", [])[::8]
        ]

    return {
        "available": True,
        "current": {
            "temp_c": current_body["main"]["temp"],
            "conditions": current_body["weather"][0]["description"],
        },
        "daily_forecast": daily,
    }


# ---- Google Places ----------------------------------------------------------

def _search_places(query: str, max_results: int) -> dict:
    api_key = config.google_places_api_key()
    if not api_key:
        return {"available": False, "reason": "Google Places API key not configured."}

    resp = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.rating,places.userRatingCount,places.formattedAddress,places.priceLevel",
        },
        json={"textQuery": query, "maxResultCount": max_results},
        timeout=_TIMEOUT,
    )
    if not resp.ok:
        return {"available": False, "reason": resp.text[:300]}

    places = [
        {
            "name": p.get("displayName", {}).get("text"),
            "address": p.get("formattedAddress"),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount"),
            "price_level": p.get("priceLevel"),
        }
        for p in resp.json().get("places", [])
    ]
    return {"available": True, "places": places}


# ---- Driving eligibility (static reference data, no live API) -------------
# There's no free, authoritative live API for IDP/reciprocity rules, so this
# is a small reference table for common demo destinations. Always framed as
# "verify before travel" — rules change and this isn't legal advice.

_DRIVING_RULES = {
    "US": {"side": "right", "idp_generally_required": False, "min_age": 16, "notes": "Most states accept a valid foreign license for short visits; some require an IDP alongside it."},
    "CA": {"side": "right", "idp_generally_required": False, "min_age": 16, "notes": "Valid foreign license usually accepted for visitors; an IDP is recommended if your license isn't in English/French."},
    "GB": {"side": "left", "idp_generally_required": False, "min_age": 17, "notes": "Valid foreign license accepted for up to 12 months; IDP recommended if license isn't in English."},
    "FR": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "Non-EU licenses generally need an IDP alongside the home license."},
    "DE": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "Non-EU visitors typically need an IDP alongside the home license."},
    "IT": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "Non-EU visitors typically need an IDP alongside the home license."},
    "ES": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "Non-EU visitors typically need an IDP alongside the home license."},
    "JP": {"side": "left", "idp_generally_required": True, "min_age": 18, "notes": "Requires a 1949 Geneva Convention IDP alongside the home license (or a certified Japanese translation for a few countries, e.g. Switzerland/Germany/France/Taiwan/Monaco/Belgium)."},
    "AU": {"side": "left", "idp_generally_required": False, "min_age": 16, "notes": "Valid foreign license usually accepted for visitors; IDP recommended if license isn't in English."},
    "NZ": {"side": "left", "idp_generally_required": False, "min_age": 16, "notes": "Valid foreign license accepted for up to 12 months; IDP recommended if license isn't in English."},
    "TH": {"side": "left", "idp_generally_required": True, "min_age": 18, "notes": "IDP generally required alongside the home license for visitors."},
    "IN": {"side": "left", "idp_generally_required": True, "min_age": 18, "notes": "IDP generally required alongside the home license for foreign visitors."},
    "MX": {"side": "right", "idp_generally_required": False, "min_age": 18, "notes": "Valid foreign license generally accepted for visitors; IDP not usually required."},
    "BR": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "IDP generally required alongside the home license for visitors."},
    "ZA": {"side": "left", "idp_generally_required": True, "min_age": 18, "notes": "IDP required unless the license is in English with a photo."},
    "AE": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "IDP generally required for visitors, though some nationalities can convert directly."},
    "SG": {"side": "left", "idp_generally_required": False, "min_age": 18, "notes": "Valid foreign license accepted for up to 12 months; IDP recommended if license isn't in English."},
    "CH": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "Non-EU visitors typically need an IDP alongside the home license."},
    "GR": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "Non-EU visitors typically need an IDP alongside the home license."},
    "KR": {"side": "right", "idp_generally_required": True, "min_age": 18, "notes": "IDP generally required alongside the home license for visitors."},
}


def _driving_requirements(destination_country_code: str, home_country_code: str) -> dict:
    dest = destination_country_code.upper()
    rules = _DRIVING_RULES.get(dest)
    if not rules:
        return {
            "available": False,
            "reason": f"No reference data for '{dest}'. Check the destination's official transport/embassy site or an IDP issuer (e.g. AAA) before renting.",
        }
    return {
        "available": True,
        "destination_country": dest,
        "drives_on": rules["side"],
        "minimum_driving_age": rules["min_age"],
        "international_driving_permit_generally_required": rules["idp_generally_required"],
        "notes": rules["notes"],
        "disclaimer": "General guidance only, not legal advice — rules vary by nationality and change over time. Confirm with the destination's official source or the car rental company before the trip.",
    }


# ---- Async FunctionTool wrappers -------------------------------------------

async def search_flights(origin: str, destination: str, departure_date: str, adults: int = 1) -> dict:
    """Search real-time flight offers between two airports.

    Args:
        origin: 3-letter IATA airport code, e.g. "JFK".
        destination: 3-letter IATA airport code, e.g. "NRT".
        departure_date: "YYYY-MM-DD".
        adults: Number of adult travelers.
    """
    return await asyncio.to_thread(_search_flights, origin, destination, departure_date, adults)


async def get_exchange_rate(base_currency: str, target_currency: str, amount: float = 1.0) -> dict:
    """Convert an amount between currencies at the current exchange rate.

    Use this to translate prices found in one currency into the traveler's
    home currency when checking their budget.

    Args:
        base_currency: 3-letter ISO code the amount is currently in, e.g. "USD".
        target_currency: 3-letter ISO code to convert into, e.g. "JPY".
        amount: The amount to convert.
    """
    return await asyncio.to_thread(_exchange_rate, base_currency, target_currency, amount)


async def get_weather_forecast(city: str) -> dict:
    """Get current weather and a multi-day forecast for a destination.

    Args:
        city: City name, e.g. "Kyoto" or "Paris,FR".
    """
    return await asyncio.to_thread(_weather_forecast, city)


async def search_places(query: str, max_results: int = 8) -> dict:
    """Search Google Places for attractions or restaurants matching a query.

    Prefer this over load_web_page when you need specific, rated venues
    (e.g. "vegetarian restaurants in Kyoto" or "museums in Paris").

    Args:
        query: Free-text search, e.g. "top attractions in Kyoto".
        max_results: Maximum number of places to return (1-20).
    """
    return await asyncio.to_thread(_search_places, query, max_results)


async def get_driving_requirements(destination_country_code: str, home_country_code: str = "US") -> dict:
    """Look up whether the traveler can drive at the destination.

    Call this before recommending a rental car — it covers which side of
    the road, the minimum driving age, and whether an International
    Driving Permit (IDP) is generally needed alongside a home license.

    Args:
        destination_country_code: 2-letter ISO code of the destination, e.g. "JP".
        home_country_code: 2-letter ISO code of the traveler's home country, e.g. "US".
    """
    return await asyncio.to_thread(_driving_requirements, destination_country_code, home_country_code)


search_flights_tool = FunctionTool(search_flights)
get_exchange_rate_tool = FunctionTool(get_exchange_rate)
get_weather_forecast_tool = FunctionTool(get_weather_forecast)
search_places_tool = FunctionTool(search_places)
get_driving_requirements_tool = FunctionTool(get_driving_requirements)
