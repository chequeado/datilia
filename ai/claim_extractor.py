"""Extract verifiable claims from a text.

Identifies claims that are likely contextualizable with country/region-level
statistical data (World Bank-style). This is a heuristic pre-screen — some
claims may still come back not_verifiable from the full pipeline.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from openai import AsyncOpenAI
from pydantic import BaseModel

import ai.llm_client as llm_client

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """\
You are a claim extraction assistant for Chequeado, a Latin American fact-checking organization.

Your job is to read a text and extract every claim that could plausibly be contextualized \
with country or region-level statistical data — the kind tracked by databases like World Bank, \
UN, OECD, or similar international organizations.

A claim is worth extracting if it:
- Makes a quantitative or measurable assertion (numbers, rates, rankings, trends)
- Refers to economic, social, demographic, health, education, or environmental indicators
- Can be compared against historical data or cross-country benchmarks
- Is about a country, region, or group of countries

Do NOT extract:
- Pure opinions or value judgments with no measurable component
- Claims about specific individuals, court cases, or one-off events
- Claims that are purely qualitative with no statistical angle
- Claims that are already self-evidently true or trivially checkable without data

For each extracted claim, quote it as it appears textually in the text. \
Do not paraphrase or merge multiple claims into one.

Return an empty list if no claims meet the criteria.
"""


class ExtractedClaim(BaseModel):
    claim: str
    rationale: str


class ClaimExtractionResult(BaseModel):
    claims: list[ExtractedClaim]


async def extract_async(text: str) -> list[ExtractedClaim]:
    client = AsyncOpenAI()
    response = await client.beta.chat.completions.parse(
        model=llm_client.MODEL,
        messages=[
            {"role": "system", "content": _INSTRUCTIONS},
            {"role": "user", "content": text},
        ],
        response_format=ClaimExtractionResult,
        temperature=0,
    )

    result = response.choices[0].message.parsed
    logger.info("[claim_extractor] extracted %d claims", len(result.claims))
    return result.claims


extract = async_to_sync(extract_async)
