"""
T046 — Eval set: synthetic personas for scoring SC-001/SC-002.

Each persona simulates a realistic user with specific needs, budget,
and preferences. The eval runner sends their messages through the agent
and scores the output against success criteria using Phoenix LLM-as-judge.

SC-001: The agent extracts structured interview slots from natural conversation
SC-002: The agent produces grounded, relevant recommendations
"""
import json
from dataclasses import dataclass, field, asdict


@dataclass
class Persona:
    """A synthetic user for evaluation."""
    id: str
    name: str
    description: str
    messages: list[str]
    expected_slots: dict[str, str]
    expected_min_results: int = 1
    tags: list[str] = field(default_factory=list)


PERSONAS: list[Persona] = [
    # --- Budget buyers ---
    Persona(
        id="p01-budget-sedan",
        name="Budget sedan buyer",
        description="Young professional looking for an affordable daily commuter",
        messages=[
            "Hi, I'm looking for a car to buy. Something cheap, maybe a sedan?",
            "My budget is around $15,000 max.",
            "I just need it for commuting to work, nothing fancy.",
        ],
        expected_slots={"category": "Sedan", "transaction_type": "buy", "budget_max": "15000"},
        tags=["budget", "sedan", "buy"],
    ),
    Persona(
        id="p02-budget-suv",
        name="Family SUV seeker",
        description="Parent needing space for kids and groceries",
        messages=[
            "I need an SUV for my family. We have two kids and a dog.",
            "Budget is up to $30,000. Want to buy, not rent.",
            "Need it by next month for a road trip.",
        ],
        expected_slots={"category": "SUV", "transaction_type": "buy", "budget_max": "30000"},
        tags=["family", "suv", "buy"],
    ),
    # --- Luxury buyers ---
    Persona(
        id="p03-luxury-sedan",
        name="Luxury sedan enthusiast",
        description="Professional wanting a premium daily driver",
        messages=[
            "I'm looking for something nice. A luxury sedan, maybe BMW or Mercedes.",
            "Budget isn't really an issue, up to $80,000.",
            "I want to buy it outright.",
        ],
        expected_slots={"category": "Sedan", "transaction_type": "buy", "budget_max": "80000"},
        tags=["luxury", "sedan", "buy"],
    ),
    Persona(
        id="p04-luxury-suv",
        name="Luxury SUV buyer",
        description="Executive wanting a premium SUV",
        messages=[
            "Looking for a high-end SUV. Something like a Range Rover or Porsche Cayenne.",
            "Budget around $100,000. Buying, not renting.",
            "Need it for both city driving and weekend getaways.",
        ],
        expected_slots={"category": "SUV", "transaction_type": "buy", "budget_max": "100000"},
        tags=["luxury", "suv", "buy"],
    ),
    # --- Renters ---
    Persona(
        id="p05-rent-weekly",
        name="Weekly rental customer",
        description="Tourist needing a car for vacation",
        messages=[
            "I need to rent a car for a week. Just something to get around town.",
            "Maybe a compact or sedan? Budget around $50 per day.",
            "I'll need it from September 15th to September 22nd.",
        ],
        expected_slots={"transaction_type": "rent", "budget_max": "350"},
        tags=["rent", "compact", "tourist"],
    ),
    Persona(
        id="p06-rent-truck",
        name="Truck rental for moving",
        description="Person moving apartments needing a truck",
        messages=[
            "I'm moving to a new apartment and need to rent a truck.",
            "Just for one day, maybe two. Something with a good bed size.",
            "Budget around $150 total.",
        ],
        expected_slots={"category": "Truck", "transaction_type": "rent", "budget_max": "150"},
        tags=["rent", "truck", "moving"],
    ),
    # --- Specific needs ---
    Persona(
        id="p07-ev-buyer",
        name="Electric vehicle enthusiast",
        description="Environmentally conscious buyer wanting an EV",
        messages=[
            "I want to go electric. Looking for an EV to buy.",
            "Budget up to $45,000. Need good range for my commute.",
            "I drive about 40 miles round trip daily.",
        ],
        expected_slots={"fuel_type": "Electric", "transaction_type": "buy", "budget_max": "45000"},
        tags=["ev", "electric", "buy"],
    ),
    Persona(
        id="p08-fuel-efficient",
        name="Fuel efficiency seeker",
        description="Commuter wanting maximum gas mileage",
        messages=[
            "I need something really fuel efficient. My gas bill is killing me.",
            "Looking to buy, budget around $20,000.",
            "I drive 60 miles round trip to work every day.",
        ],
        expected_slots={"transaction_type": "buy", "budget_max": "20000"},
        tags=["fuel-efficient", "commuter", "buy"],
    ),
    Persona(
        id="p09-family-minivan",
        name="Minivan parent",
        description="Large family needing maximum passenger space",
        messages=[
            "We have 4 kids and need something that fits everyone plus gear.",
            "A minivan or large SUV. Budget up to $35,000 to buy.",
            "Need it for school runs and soccer practice.",
        ],
        expected_slots={"transaction_type": "buy", "budget_max": "35000"},
        tags=["family", "minivan", "large-family"],
    ),
    Persona(
        id="p10-sports-car",
        name="Weekend sports car",
        description="Enthusiast wanting a fun weekend car",
        messages=[
            "I want something fun to drive on weekends. A sports car or convertible.",
            "Budget around $50,000. Buying outright.",
            "Already have a daily driver, this is just for fun.",
        ],
        expected_slots={"transaction_type": "buy", "budget_max": "50000"},
        tags=["sports", "fun", "weekend"],
    ),
    # --- Edge cases ---
    Persona(
        id="p11-vague",
        name="Vague user",
        description="User who gives minimal information",
        messages=[
            "I need a car.",
        ],
        expected_slots={},
        expected_min_results=0,
        tags=["vague", "edge-case"],
    ),
    Persona(
        id="p12-contradictory",
        name="Contradictory requirements",
        description="User whose requirements conflict",
        messages=[
            "I want a luxury SUV to buy for under $10,000.",
            "It needs to be brand new with less than 100 miles.",
        ],
        expected_slots={"category": "SUV", "transaction_type": "buy", "budget_max": "10000"},
        tags=["contradictory", "edge-case"],
    ),
    Persona(
        id="p13-multi-turn",
        name="Multi-turn conversation",
        description="User who changes their mind multiple times",
        messages=[
            "I'm looking for a sedan to rent.",
            "Actually, make that an SUV. And I want to buy, not rent.",
            "Wait, my budget is only $12,000. Can I still get an SUV?",
            "Okay fine, what about a sedan then?",
        ],
        expected_slots={"category": "Sedan", "transaction_type": "buy", "budget_max": "12000"},
        tags=["multi-turn", "change-mind"],
    ),
    Persona(
        id="p14-location-specific",
        name="Location-focused buyer",
        description="User who cares about local availability",
        messages=[
            "I need a car in Austin, TX. Something reliable for $20,000.",
            "I want to buy a sedan or hatchback.",
            "Preferably something with low mileage.",
        ],
        expected_slots={"transaction_type": "buy", "budget_max": "20000", "location": "Austin, TX"},
        tags=["location", "specific"],
    ),
    Persona(
        id="p15-rent-luxury",
        name="Luxury rental for event",
        description="User renting a premium car for a special occasion",
        messages=[
            "I'm attending a wedding next weekend and need to rent something impressive.",
            "A luxury sedan or sports car. Budget up to $200 per day.",
            "Need it for Saturday and Sunday.",
        ],
        expected_slots={"transaction_type": "rent", "budget_max": "400"},
        tags=["rent", "luxury", "event"],
    ),
]


def get_personas() -> list[Persona]:
    """Return all eval personas."""
    return PERSONAS


def get_persona_by_id(persona_id: str) -> Persona | None:
    """Look up a persona by ID."""
    return next((p for p in PERSONAS if p.id == persona_id), None)


def export_personas_json(path: str = "eval/personas.json") -> None:
    """Export personas to JSON for external tools."""
    data = [asdict(p) for p in PERSONAS]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
