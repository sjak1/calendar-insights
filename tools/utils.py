"""
Utility tool functions.
"""

fruits = ["apple", "banana", "guava", "mango"]


def get_fruits():
    """Get list of fruits."""
    return fruits


def add_fruit(fruit):
    """Add a fruit to the list."""
    fruits.append(fruit)
    return fruits


def oracle_financial_stats(year):
    """Get financial stats for a given year."""
    if year == "2024":
        return {
            "profit": 1000000,
            "revenue": 2000000,
            "expenses": 1000000,
            "net_income": 1000000,
            "gross_profit": 1000000,
            "gross_margin": 0.5,
            "net_margin": 0.5,
            "return_on_assets": 0.5,
            "return_on_equity": 0.5,
        }
    elif year == "2025":
        return {
            "profit": 1500000,
            "revenue": 2500000,
            "expenses": 1500000,
            "net_income": 500000,
            "gross_profit": 1000000,
            "gross_margin": 0.5,
            "net_margin": 0.5,
            "return_on_assets": 0.5,
            "return_on_equity": 0.5,
        }


def get_horoscope(sign):
    """Get horoscope for a sign."""
    return f"{sign}: next tuesday you will befriend a baby otter or a baby seal."
