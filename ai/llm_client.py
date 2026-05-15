import os

from config import settings

# The OpenAI Agents SDK reads OPENAI_API_KEY from the environment.
# pydantic-settings loads .env into Python objects but not os.environ,
# so we bridge that here.
os.environ.setdefault("OPENAI_API_KEY", settings.OPENAI_API_KEY)

MODEL = settings.OPENAI_MODEL
TEMPERATURE = settings.LLM_TEMPERATURE
