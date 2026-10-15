"""Step 3: one Gemini call on Vertex AI, using Application Default Credentials."""
import os

from google import genai

client = genai.Client(
    vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
)
r = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    contents="Reply with the single word: ready",
)
print(r.text)
