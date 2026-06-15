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
logger.setLevel(logging.DEBUG)

VERIFIER_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "You are a strict photo auditor for a plastic-WASTE collection program "
    "in Indonesia. Your job is to REJECT photos that are not genuine "
    "plastic-waste collection reports.\n\n"
    "DEFAULT VERDICT IS 'fail'. You only upgrade to 'pass' when there is "
    "POSITIVE, UNAMBIGUOUS evidence that the photo shows plastic waste "
    "that has been collected and gathered for recycling/disposal. If you "
    "have to guess, mark 'fail'. If something looks plausible but you "
    "cannot confirm, mark 'suspect'. Never give the benefit of the doubt."
)


def _build_prompt(reported_kg: float, volunteer_area: str) -> str:
    return (
        f"Audit this plastic-WASTE collection report photo.\n"
        f"Reported: {reported_kg} kg from {volunteer_area}.\n\n"
        f"Return ONLY valid JSON with this exact shape:\n"
        "{\n"
        "  'has_plastic': bool,\n"
        "  'is_collected_waste': bool,\n"
        "  'positive_indicators': [list of short strings — what evidence "
        "supports this being a real collection? Empty list if none.],\n"
        "  'negative_indicators': [list of short strings — what is "
        "suspicious / disqualifying about the photo?],\n"
        "  'has_scale': bool,\n"
        "  'scale_reading': float or null,\n"
        "  'photo_seems_fresh': bool,\n"
        "  'verdict': 'pass' or 'suspect' or 'fail',\n"
        "  'confidence': 'high' or 'medium' or 'low',\n"
        "  'reason_id': 'short reason in Indonesian (max 20 words)'\n"
        "}\n\n"
        "============================================================\n"
        "WHAT COUNTS AS PLASTIC WASTE COLLECTION (positive)\n"
        "============================================================\n"
        "* A pile, sack, bag, bin, or heap of MULTIPLE used plastic items "
        "  (bottles, kresek, sachets, wrappers, cups, PET, HDPE, etc.).\n"
        "* Items look used / dirty / crushed / mixed — clearly destined "
        "  for recycling or disposal, not for sale.\n"
        "* The plastic waste is the dominant subject of the photo.\n"
        "* Bonus signal: a weighing scale visible with the waste pile, or "
        "  a volunteer / sack at a collection point.\n\n"
        "============================================================\n"
        "WHAT DOES NOT COUNT — verdict MUST be 'fail'\n"
        "============================================================\n"
        "Reject the photo whenever ANY of these is true:\n"
        " (A) No plastic visible at all: selfies, faces, food, drinks, "
        "     animals, vehicles, scenery, screenshots, blank walls.\n"
        " (B) Plastic IS visible but is still part of an item in everyday "
        "     use — NOT collected waste. Examples:\n"
        "     - cables, wires, chargers, electronics, phone cases\n"
        "     - chairs, buckets, toys, kitchenware, appliances, helmets\n"
        "     - sealed/unopened product packaging on store shelves\n"
        "     - single intact bottle/cup/bag being held or on a table\n"
        "     - clothes, shoes, bags worn or on display\n"
        " (C) The plastic appears as background or incidental (e.g. you "
        "     can see a plastic bag in the corner but the photo is about "
        "     something else).\n"
        " (D) Only a single small item shown — inconsistent with a "
        "     plastic-WASTE collection that is supposed to weigh "
        f"     {reported_kg} kg.\n"
        " (E) The photo is of a screen, monitor, printout, or another "
        "     photo (re-uploads of internet images).\n"
        " (F) The 'plastic' is actually paper, fabric, foil, glass, "
        "     ceramic, metal, or other material.\n"
        " (G) The photo is too blurry, too dark, or too cropped to "
        "     identify the subject with confidence.\n\n"
        "============================================================\n"
        "WHEN TO USE 'suspect' INSTEAD OF 'fail'\n"
        "============================================================\n"
        "Mark 'suspect' (not 'fail') only when plastic waste IS clearly "
        "the subject, but one of these is true:\n"
        " * Visible scale reading differs from reported kg by >30%.\n"
        " * Quantity of plastic clearly inconsistent with reported kg "
        "   (e.g. half a bag but reported 20 kg).\n"
        " * Photo composition makes it hard to confirm quantity (e.g. "
        "   only the top of a sack is visible).\n\n"
        "============================================================\n"
        "WHEN TO USE 'pass'\n"
        "============================================================\n"
        "Use 'pass' ONLY when ALL of the following hold:\n"
        " 1. has_plastic == true\n"
        " 2. is_collected_waste == true\n"
        " 3. positive_indicators is NON-EMPTY and lists at least one "
        "    concrete observation (pile size, sack, mixed items, etc.).\n"
        " 4. negative_indicators is empty or contains only minor caveats.\n"
        " 5. confidence is 'medium' or 'high'.\n"
        "If any of those fail → use 'suspect' or 'fail'.\n\n"
        "============================================================\n"
        "WORKED EXAMPLES (do not output these — for your reference only)\n"
        "============================================================\n"
        "* Photo of tangled USB cables on a desk → fail "
        "(category B: item in use; not waste).\n"
        "* Photo of a single intact mineral water bottle on a table → "
        "fail (category D + B).\n"
        "* Photo of a plastic chair in a room → fail (category B).\n"
        "* Photo of a person holding a phone → fail (category A/B).\n"
        "* Photo of an open sack on the ground with mixed crushed bottles "
        "and kresek inside → pass.\n"
        "* Photo of a weighing scale showing 5.2 kg next to a clear bag "
        "of bottles → pass.\n"
        "* Photo of a small pile of 3 bottles, reported 15 kg → suspect "
        "(quantity mismatch).\n"
        "* Blurry photo where you cannot tell what's inside the bag → "
        "fail (category G).\n\n"
        "Now audit the attached image and output JSON only."
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
        logger.info("PhotoVerifier raw=%s parsed=%s", raw, verdict)
        verdict = self._enforce_pass_gates(verdict)
        verdict["should_flag"] = verdict.get("verdict") != "pass"
        verdict["flag_reason"] = (
            f"Foto: {verdict.get('reason_id', '')}"
            if verdict["should_flag"]
            else None
        )
        logger.info(
            "PhotoVerifier final verdict=%s should_flag=%s reason=%s",
            verdict.get("verdict"),
            verdict.get("should_flag"),
            verdict.get("reason_id"),
        )
        return verdict

    @staticmethod
    def _enforce_pass_gates(verdict: dict[str, Any]) -> dict[str, Any]:
        """Override a 'pass' verdict when the structured signals don't agree.

        The model occasionally returns ``verdict='pass'`` even when its own
        fields (``has_plastic``, ``is_collected_waste``, ``confidence``,
        ``positive_indicators``) contradict that. We downgrade defensively
        so a non-waste photo can't slip through on a single ambiguous call.
        """
        if verdict.get("verdict") != "pass":
            return verdict

        has_plastic = verdict.get("has_plastic")
        is_waste = verdict.get("is_collected_waste")
        confidence = (verdict.get("confidence") or "").lower()
        positive = verdict.get("positive_indicators") or []
        negative = verdict.get("negative_indicators") or []

        # No plastic at all → fail outright.
        if has_plastic is False:
            verdict["verdict"] = "fail"
            verdict["reason_id"] = (
                verdict.get("reason_id")
                or "Tidak terlihat plastik pada foto"
            )
            return verdict

        # Plastic present but not collected waste (cables, items in use,
        # packaging on a product, etc.) → fail.
        if is_waste is False:
            verdict["verdict"] = "fail"
            verdict["reason_id"] = (
                verdict.get("reason_id")
                or "Plastik bukan sampah hasil pengumpulan (masih melekat pada barang yang dipakai)"
            )
            return verdict

        # Low confidence, empty positive indicators, or negative indicators
        # outnumbering positive → demote to 'suspect' for fasilitator review.
        if (
            confidence == "low"
            or not positive
            or len(negative) > len(positive)
        ):
            verdict["verdict"] = "suspect"
            verdict["reason_id"] = (
                verdict.get("reason_id")
                or "Foto tidak meyakinkan sebagai laporan pengumpulan plastik"
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
            logger.info(
                "PhotoVerifier SKIP — fasilitator_relay source (no model call)"
            )
            return {
                "verdict": "skipped",
                "should_flag": False,
                "flag_reason": None,
                "reason": "Diverifikasi fasilitator",
            }

        if not photo_url:
            if require_photo:
                logger.info("PhotoVerifier SKIP — no photo, asking for one")
                return {
                    "verdict": "no_photo",
                    "should_flag": False,
                    "needs_photo": True,
                    "message": (
                        "Laporan perlu disertai foto. "
                        "Tolong kirim foto plastik + timbangan 📸"
                    ),
                }
            logger.info(
                "PhotoVerifier SKIP — no photo, accepted without verification"
            )
            return {
                "verdict": "no_photo_ok",
                "should_flag": False,
                "flag_reason": "Laporan tanpa foto (masih diterima)",
            }

        logger.info(
            "PhotoVerifier RUN — url=%s reported_kg=%s area=%s",
            photo_url, reported_kg, volunteer_area,
        )
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
