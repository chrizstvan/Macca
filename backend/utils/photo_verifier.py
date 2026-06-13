"""Vision-based verification of plastic-collection report photos."""

import base64
import json
import logging
import re
from typing import Any

import anthropic
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

VERIFIER_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "You are a photo verification assistant for a plastic collection program "
    "in Indonesia. Be practical and fair — most volunteers are honest. Only "
    "flag clearly suspicious cases."
)


def _build_prompt(reported_kg: float, volunteer_area: str) -> str:
    return (
        f"Verify this plastic collection report photo.\n"
        f"Reported: {reported_kg} kg from {volunteer_area}.\n\n"
        f"Return ONLY valid JSON:\n"
        "{\n"
        "  'has_plastic': bool,\n"
        "  'has_scale': bool,\n"
        "  'scale_reading': float or null,\n"
        "  'photo_seems_fresh': bool,\n"
        "  'verdict': 'pass' or 'suspect' or 'fail',\n"
        "  'confidence': 'high' or 'medium' or 'low',\n"
        "  'reason_id': 'short reason in Indonesian (max 20 words)'\n"
        "}\n\n"
        "Verdict rules:\n"
        "- 'fail': photo clearly has NO plastic (selfie, food, random object)\n"
        "- 'suspect': has scale but reading differs from reported by >30%, "
        "OR very low confidence\n"
        "- 'pass': everything else (give benefit of doubt)"
    )


class PhotoVerifier:
    """Uses Claude vision to score report photos and emit a structured verdict."""

    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def verify_photo(
        self,
        photo_url: str,
        reported_kg: float,
        volunteer_area: str,
    ) -> dict[str, Any]:
        """Download the photo, run vision verification, return the verdict dict."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(photo_url)
                resp.raise_for_status()
                image_bytes = resp.content
                media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        except httpx.HTTPError as exc:
            logger.error("PhotoVerifier could not fetch %s: %s", photo_url, exc)
            return self._error_verdict("Foto tidak dapat diunduh untuk verifikasi")

        image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")

        try:
            response = await self.client.messages.create(
                model=VERIFIER_MODEL,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": _build_prompt(reported_kg, volunteer_area),
                            },
                        ],
                    }
                ],
            )
            raw = response.content[0].text
        except anthropic.APIError as exc:
            logger.error("PhotoVerifier Claude error: %s", exc)
            return self._error_verdict("Verifikasi foto gagal sementara")

        verdict = self._parse_verdict(raw)
        verdict["should_flag"] = verdict.get("verdict") != "pass"
        verdict["flag_reason"] = (
            f"Foto: {verdict.get('reason_id', '')}"
            if verdict["should_flag"]
            else None
        )
        return verdict

    async def verify_or_skip(
        self,
        photo_url: str | None,
        reported_kg: float,
        volunteer_area: str,
        is_fasilitator_relay: bool,
        require_photo: bool = True,
    ) -> dict[str, Any]:
        """Apply policy gates around verify_photo (skip / no-photo / verify)."""
        if is_fasilitator_relay:
            return {
                "verdict": "skipped",
                "should_flag": False,
                "flag_reason": None,
                "reason": "Diverifikasi fasilitator",
            }

        if not photo_url:
            if require_photo:
                return {
                    "verdict": "no_photo",
                    "should_flag": False,
                    "needs_photo": True,
                    "message": (
                        "Laporan perlu disertai foto. "
                        "Tolong kirim foto plastik + timbangan 📸"
                    ),
                }
            return {
                "verdict": "no_photo_ok",
                "should_flag": False,
                "flag_reason": "Laporan tanpa foto (masih diterima)",
            }

        return await self.verify_photo(photo_url, reported_kg, volunteer_area)

    @staticmethod
    def _parse_verdict(raw: str) -> dict[str, Any]:
        """Extract the JSON object the model returned, tolerating single quotes."""
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("PhotoVerifier got no JSON in: %r", raw)
            return PhotoVerifier._error_verdict("Verifikasi foto: format respon tidak valid")
        text = match.group(0)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                return json.loads(text.replace("'", '"'))
            except json.JSONDecodeError:
                logger.warning("PhotoVerifier could not parse JSON: %r", text)
                return PhotoVerifier._error_verdict("Verifikasi foto: format respon tidak valid")

    @staticmethod
    def _error_verdict(reason: str) -> dict[str, Any]:
        return {
            "has_plastic": False,
            "has_scale": False,
            "scale_reading": None,
            "photo_seems_fresh": False,
            "verdict": "suspect",
            "confidence": "low",
            "reason_id": reason,
            "should_flag": True,
            "flag_reason": f"Foto: {reason}",
        }
