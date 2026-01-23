"""
Simple demo of OpenAI Structured Outputs (.parse())

Shows the difference between regular API and .parse() API
"""
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv
import json

load_dotenv()
client = OpenAI()


# ============================================================================
# SIMPLE MODEL: Dog
# ============================================================================

class Dog(BaseModel):
    """A simple dog model."""
    name: str = Field(description="Dog's name")
    breed: str = Field(description="Breed like 'Labrador' or 'Golden Retriever'")
    age: int = Field(description="Age in years", ge=0, le=20)
    weight: float = Field(description="Weight in kg", gt=0)
    is_good_boy: bool = Field(default=True, description="Is this a good boy?")


# ============================================================================
# DEMO 1: Regular API (returns text)
# ============================================================================

print("=" * 80)
print("DEMO 1: Regular API (returns free text)")
print("=" * 80)

response1 = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Tell me about a dog named Buddy who is a 3-year-old Labrador weighing 25kg."}
    ],
    temperature=0.7,
)

print("\n📝 RAW RESPONSE TYPE:", type(response1))
print("📝 RESPONSE CONTENT:")
print(response1.choices[0].message.content)
print("\n❌ Problem: It's just text! You'd have to parse it manually with regex/JSON.")


# ============================================================================
# DEMO 2: Structured Output (.parse()) - Returns typed object
# ============================================================================

print("\n\n" + "=" * 80)
print("DEMO 2: Structured Output (.parse()) - Returns typed object")
print("=" * 80)

response2 = client.beta.chat.completions.parse(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant. Return information about dogs."},
        {"role": "user", "content": "Tell me about a dog named Buddy who is a 3-year-old Labrador weighing 25kg."}
    ],
    response_format=Dog,  # ← This forces LLM to return Dog object
    temperature=0.7,
)

print("\n📝 RAW RESPONSE TYPE:", type(response2))
print("📝 RESPONSE OBJECT:", response2)
print("\n✅ PARSED DOG TYPE:", type(response2.choices[0].message.parsed))
print("✅ PARSED DOG OBJECT:")
dog = response2.choices[0].message.parsed
print(f"   Name: {dog.name}")
print(f"   Breed: {dog.breed}")
print(f"   Age: {dog.age}")
print(f"   Weight: {dog.weight}kg")
print(f"   Is Good Boy: {dog.is_good_boy}")

print("\n✅ ACCESS DIRECTLY (no parsing needed!):")
print(f"   dog.name = '{dog.name}'")
print(f"   dog.age = {dog.age}")

print("\n✅ CONVERT TO DICT:")
print(json.dumps(dog.model_dump(), indent=2))


# ============================================================================
# DEMO 3: Show what happens if LLM tries to return wrong format
# ============================================================================

print("\n\n" + "=" * 80)
print("DEMO 3: Validation - What if LLM returns invalid data?")
print("=" * 80)

try:
    response3 = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Create a dog with age -5 and weight 0."}  # Invalid!
        ],
        response_format=Dog,
        temperature=0.7,
    )
    dog3 = response3.choices[0].message.parsed
    print("✅ Dog created:", dog3)
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
    print("   → Pydantic validates the data automatically!")


# ============================================================================
# DEMO 4: Compare JSON output
# ============================================================================

print("\n\n" + "=" * 80)
print("DEMO 4: JSON Output Comparison")
print("=" * 80)

print("\n📊 Regular API returns:")
print("   Type: str (text)")
print("   You must: json.loads() manually")
print("   Validation: None (you check yourself)")

print("\n📊 .parse() API returns:")
print("   Type: Dog (Pydantic object)")
print("   You can: Access dog.name directly")
print("   Validation: Automatic (age >= 0, weight > 0)")

print("\n" + "=" * 80)
print("SUMMARY: .parse() gives you typed, validated objects automatically!")
print("=" * 80)

