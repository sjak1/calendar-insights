"""
External API integrations.
"""
import requests
from dotenv import load_dotenv

load_dotenv()


def get_gdp(country, year):
    """Get GDP data for a country and year from API Ninjas."""
    url = "https://api.api-ninjas.com/v1/gdp"
    headers = {"X-Api-Key": "QxU+IiicXDXJonqyCUJGHw==1pyYpxF0JDK4LMPy"}

    params = {"country": country, "year": year}
    res = requests.get(url, headers=headers, params=params)
    if res.ok:
        return res.json()
    else:
        return ("error:", res.status_code, res.text)
