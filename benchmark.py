"""Benchmark Jev alone, and Jev + Gemini, on a Kaggle customer-support dataset.

Dataset: bitext/bitext-gen-ai-chatbot-customer-support-dataset (Kaggle)
  - Bitext's hybrid synthetic customer-service requests, about 1,000 per intent
  - Label: `category` (default, 11 queues) or `intent` (27, much harder) via LABEL=intent
  - Each category is described by the dataset's own intents (DESCRIBE_LABELS=0 for bare names)
  - Bitext publishes this dataset under CDLA-Sharing 1.0

Run:  ESCALATE=0 python benchmark.py      Jev only (Part 1)
      python benchmark.py                 Jev + Gemini (Part 2)
      N_PER_QUEUE=20 python benchmark.py  bigger sample
Writes queues.json (used by the Cloud Run app) and results.csv.
"""
import glob
import json
import os
import statistics

import kagglehub
import pandas as pd

from triage import ESCALATE, GEMINI_MODEL, GEMINI_THINKING_LEVEL, THRESHOLD, triage

DATASET = "bitext/bitext-gen-ai-chatbot-customer-support-dataset"
LABEL = os.getenv("LABEL", "category")
DESCRIBE_LABELS = os.getenv("DESCRIBE_LABELS", "1") != "0"
N_PER_QUEUE = int(os.getenv("N_PER_QUEUE", "5"))
SEED = int(os.getenv("SEED", "0"))
NEEDED = {"instruction", LABEL}


def load_tickets() -> tuple[pd.DataFrame, dict]:
    path = kagglehub.dataset_download(DATASET)
    # Take the largest CSV that has the columns we need.
    best = None
    for f in glob.glob(os.path.join(path, "**", "*.csv"), recursive=True):
        df = pd.read_csv(f)
        if NEEDED <= set(df.columns) and (best is None or len(df) > len(best[1])):
            best = (f, df)
    if best is None:
        raise SystemExit(f"No CSV in {path} has columns {NEEDED}")
    f, df = best
    print(f"Using {os.path.basename(f)}: {len(df)} rows, label = {LABEL}")

    df = df.dropna(subset=["instruction", LABEL]).rename(columns={LABEL: "queue"})
    queues = sorted(df["queue"].unique())
    # groupby().sample keeps all columns (newer pandas drops the group key from groupby().apply)
    n = min(N_PER_QUEUE, int(df["queue"].value_counts().min()))
    sample = df.groupby("queue").sample(n=n, random_state=SEED).reset_index(drop=True)
    sample["text"] = sample["instruction"].astype(str)

    # Describe each category by the dataset's own intents (no hand-written text).
    labels = {q: None for q in queues}
    if DESCRIBE_LABELS and LABEL == "category" and "intent" in df.columns:
        for q, intents in df.groupby("queue")["intent"].unique().items():
            labels[q] = "Requests about " + ", ".join(sorted(i.replace("_", " ") for i in intents))
    print(f"{len(queues)} labels, {len(sample)} requests sampled (seed {SEED})\n")
    return sample, labels


def main() -> None:
    sample, queues = load_tickets()
    with open("queues.json", "w") as fh:
        json.dump(queues, fh, indent=2)

    rows = []
    for i, t in sample.iterrows():
        r = triage(t["text"], queues)
        jev = r["jev"] or {}
        rows.append({
            "want": t["queue"],
            "jev": jev.get("queue", ""),
            "confidence": jev.get("confidence", float("nan")),
            "p_injection": jev.get("p_injection", float("nan")),
            "path": r["path"],
            "final": r["final"],
            "error": r.get("error", ""),
            "total_ms": r["total_ms"],
            "gemini_reason": r.get("gemini", {}).get("reason", ""),
            "probabilities": json.dumps(jev.get("probabilities", {})),
            "text": t["text"][:300],
        })
        print(f"[{i + 1:>3}/{len(sample)}] {r['path']:6} conf={jev.get('confidence', float('nan')):.2f} "
              f"{r['final'][:28]:28} want={t['queue'][:28]}" + (f"  ERROR({r['error']})" if r.get("error") else ""))

    res = pd.DataFrame(rows)
    res.to_csv("results.csv", index=False)
    summarize(res)


def summarize(res: pd.DataFrame) -> None:
    n = len(res)
    mode = "jev+gemini" if ESCALATE else "jev only"
    model = f", {GEMINI_MODEL} thinking={GEMINI_THINKING_LEVEL}" if ESCALATE else ""
    print(f"\n--- {n} requests, label {LABEL}, mode {mode}, threshold {THRESHOLD}{model} ---")

    answered = res[res.jev != ""]
    hi = answered[answered.confidence >= THRESHOLD]
    lo = answered[answered.confidence < THRESHOLD]
    print(f"Jev's pick correct:            {(answered.jev == answered.want).mean():.0%}  (n={len(answered)})")
    print(f"  Jev confidence >= {THRESHOLD}:     {(hi.jev == hi.want).mean():.0%} correct  (n={len(hi)})")
    if len(lo):
        print(f"  Jev confidence <  {THRESHOLD}:     {(lo.jev == lo.want).mean():.0%} correct  (n={len(lo)})")

    print(f"Final answer correct:          {(res.final == res.want).mean():.0%}")
    slow = res[res.path == "gemini"]
    if ESCALATE:
        print(f"Escalated to Gemini:           {len(slow)}/{n}")
        if len(slow):
            print(f"  on those, Jev's pick correct {(slow.jev == slow.want).sum()}, "
                  f"Gemini correct {(slow.final == slow.want).sum()}")
    print(f"Sent to human (injection):     {((res.path == 'human') & (res.error == '')).sum()}/{n}"
          "  (dataset has none -> false positives)")
    if (res.error != "").any():
        print(f"Sent to human (API error):     {(res.error != '').sum()}/{n}")
    for path in ("jev", "gemini"):
        g = res[res.path == path]
        if len(g):
            print(f"{'Median latency, ' + path + ' path:':31}{statistics.median(g.total_ms):.0f} ms")

    errors = res[(res.final != res.want) & (res.path != "human")]
    if len(errors):
        print("Mistakes (want -> got):")
        print(errors.groupby(["want", "final"]).size().sort_values(ascending=False).to_string())
    print("\nPer-request detail incl. Jev probabilities and Gemini's reasons: results.csv")


if __name__ == "__main__":
    main()
