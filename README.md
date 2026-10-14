# Jev + Gemini ticket routing on Google Cloud

A support-ticket router where [Jev](https://docs.typesafe.ai) (TypeSafe AI's "System One" decision model) answers every request in one fast, typed call, and **Gemini on Vertex AI** takes over only for the requests Jev isn't confident about, returning a written reason for each. The service runs on **Cloud Run**, with the API key in **Secret Manager**.

Companion code for the Medium series:
- Part 1: How far does Jev get on its own? **[LINK TO PART 1]**
- Part 2: Adding Gemini on Google Cloud: **[LINK TO PART 2]**

```
ticket ──► Jev (Choice + Noul, one call)
              │
              ├─ looks like prompt injection ─────► human
              ├─ confidence ≥ 0.85 ───────────────► route (fast path)
              ├─ confidence < 0.85 ──► Gemini on Vertex AI ──► route + reason
              └─ any API failure ─────────────────► human
```

## Results

<!-- Update after the 220-request run; keep n, seed, and settings next to the numbers. -->
55 requests from the Bitext dataset (5 per category, 11 categories, seed 0), queues described by the dataset's own intents:

| | Jev alone | Jev + Gemini (threshold 0.85) |
|---|---|---|
| Correct | 93–95% (across runs) | **98% (54/55)** |
| Handled by Jev's fast path | 55 (median 141–157 ms) | 50, all correct |
| Escalated to Gemini | – | 5 (Gemini correct on 4; median 3.5 s) |

Across three runs, Jev was right on 50 of 50, 50 of 50, and 50 of 51 requests where its confidence was at least 0.85, and usually wrong below it. That's why escalating only the uncertain requests works: Gemini sees fewer than 1 in 10 requests, and those are where nearly all of Jev's mistakes are. Median latency for Jev's path was 136–168 ms; Gemini's path varied widely between sessions, so measure it yourself. This is a small, synthetic sample: read the numbers as direction, not effect size.

## Quickstart

**Part 1 (Jev only)** needs Python 3.12, a [TypeSafe API key](https://console.typesafe.ai), and a [Kaggle API token](https://www.kaggle.com/settings/api). No Google Cloud setup.

```bash
git clone <this repo> && cd jev-gcp-triage
conda create -n jev python=3.12 -y && conda activate jev
pip install -r requirements.txt
export TYPESAFE_API_KEY=...

# Kaggle token, kept out of shell history (zsh)
mkdir -p ~/.kaggle
read -s "TOKEN?Paste Kaggle token: " && printf %s "$TOKEN" > ~/.kaggle/access_token && unset TOKEN
chmod 600 ~/.kaggle/access_token

python step2_hello_jev.py          # one Jev call
ESCALATE=0 python benchmark.py     # Jev alone on the Kaggle sample
```

**Part 2 (Jev + Gemini)** adds the [gcloud CLI](https://cloud.google.com/sdk/docs/install) and a Google Cloud project with billing enabled:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global

gcloud auth application-default login
gcloud config set project $GOOGLE_CLOUD_PROJECT
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT
gcloud services enable aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com --project $GOOGLE_CLOUD_PROJECT

python step3_hello_gemini.py       # one Gemini call; prints "ready"
python benchmark.py                # Jev + Gemini; writes results.csv and queues.json
```

## Deploy to Cloud Run

Run `benchmark.py` first: the container includes the `queues.json` it writes.

```bash
printf %s "$TYPESAFE_API_KEY" | gcloud secrets create typesafe-api-key --data-file=-

PN=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT --format='value(projectNumber)')
SA=$PN-compute@developer.gserviceaccount.com
gcloud secrets add-iam-policy-binding typesafe-api-key \
  --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
  --member=serviceAccount:$SA --role=roles/aiplatform.user

gcloud run deploy jev-triage --source . --region us-central1 --no-allow-unauthenticated \
  --set-secrets TYPESAFE_API_KEY=typesafe-api-key:latest \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=global

URL=$(gcloud run services describe jev-triage --region us-central1 --format='value(status.url)')
curl -s -X POST "$URL/triage" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" -H "Content-Type: application/json" \
  -d '{"text":"I was billed twice for March. Please refund one charge."}'; echo
```

Clean up with `gcloud run services delete jev-triage --region us-central1` and `gcloud secrets delete typesafe-api-key`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ESCALATE` | `1` | `0` = Jev only, never call Gemini |
| `JEV_CONFIDENCE_THRESHOLD` | `0.85` | Jev confidence needed to skip Gemini |
| `JEV_INJECTION_P` | `0.5` | Injection probability that sends a ticket to a human |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Model for escalated requests |
| `GEMINI_THINKING_LEVEL` | `LOW` | `default` uses the model's own default |
| `MAX_TICKET_CHARS` | `8000` | Request size limit for the API |
| `LABEL` | `category` | Benchmark label: `category` (11) or `intent` (27) |
| `DESCRIBE_LABELS` | `1` | `0` = bare queue names, no descriptions |
| `N_PER_QUEUE`, `SEED` | `5`, `0` | Benchmark sample size and seed |

## Project structure

```
triage.py               Router: Jev call, Gemini call, routing policy, failure fallback
benchmark.py            Loads the Kaggle dataset, runs the router, prints metrics
main.py                 FastAPI app for Cloud Run (/health, /triage)
step2_hello_jev.py      Smoke test: one Jev call
step3_hello_gemini.py   Smoke test: one Gemini call
queues.json             Queue names and descriptions (written by benchmark.py)
requirements.txt        Everything, for local runs
requirements-serve.txt  Serving dependencies only, for the container
Dockerfile              Non-root container for Cloud Run
```

## Security notes

- No secrets in the repo: the TypeSafe key comes from Secret Manager on Cloud Run and from your environment locally; Gemini uses Application Default Credentials.
- The Cloud Run service requires an authenticated caller.
- Both models can only answer with one of the configured queue names, which limits what a malicious ticket can do. The injection check adds a probabilistic filter on top; it is not a security boundary.
- Gemini's routing instructions sit in the system instruction, and the ticket is delimited and treated as data.
- Any API failure routes the ticket to a human, and only the error type is logged, never ticket text.
- Before using real customer data: ticket text is sent to TypeSafe's API, outside Google Cloud, so review TypeSafe's data terms. Run Cloud Run as a dedicated service account rather than the default compute account, and escape Gemini's `reason` field before displaying it in a web page.

## Dataset

[Bitext Gen AI Chatbot Customer Support Dataset](https://www.kaggle.com/datasets/bitext/bitext-gen-ai-chatbot-customer-support-dataset), © Bitext Innovations, released under the Community Data License Agreement – Sharing 1.0. The dataset is downloaded at runtime and is not redistributed in this repository.

## License

Code: **[YOUR LICENSE]**. The dataset keeps its own license (see above).
