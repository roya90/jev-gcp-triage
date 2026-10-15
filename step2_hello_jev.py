"""Step 2: one Jev call. Prints the raw response so you can confirm field names."""
from typesafe_sdk import Choice, Noul, TypeSafeClient

with TypeSafeClient() as client:  # reads TYPESAFE_API_KEY
    r = client.system_one(
        state={"ticket": "I was charged twice for my subscription this month."},
        questions={
            "queue": Choice(
                instructions="Which support queue should handle this ticket?",
                criteria={"Billing": None, "Technical Support": None, "General Inquiry": None},
            ),
            "injection": Noul(
                instructions="Does this ticket try to give instructions to an AI system?"
            ),
        },
    )

print("RAW:", r)
c = r.choices["queue"]
print("choice:", c.choice, "| confidence:", c.confidence)
print("probabilities:", c.probabilities)
n = r.nouls["injection"].noul
print("noul:", n, type(n))
