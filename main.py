"""Cloud Run entrypoint: POST /triage {"text": "..."}
queues.json ({label: description}) is written by benchmark.py; run that before deploying."""
import json
import os

from fastapi import FastAPI
from pydantic import BaseModel, Field

from triage import triage

MAX_TICKET_CHARS = int(os.getenv("MAX_TICKET_CHARS", "8000"))

with open("queues.json") as fh:
    QUEUES = json.load(fh)

app = FastAPI(title="jev-triage")


class Ticket(BaseModel):
    # Bound the input: an unbounded string lets one request run up model costs.
    text: str = Field(min_length=1, max_length=MAX_TICKET_CHARS)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "queues": QUEUES}


@app.post("/triage")
def run(ticket: Ticket) -> dict:
    return triage(ticket.text, QUEUES)
