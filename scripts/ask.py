from sqlite_qa import ask_sqlite
import get_gdp

questions = [
    "Give me the names of the executives attending today ?",
    "Who is attending from Deloitte next week?",
    "Find an presenter available on 12th Dec on topic IOT for a customer session.",
    "Check if the IBM visit on Dec 14 has all presenters assigned.",
    "how many meetings are submitted in this month"
]

for question in questions:
    print(question)
    print(get_gdp.handle_query(question, None))