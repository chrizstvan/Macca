"""Education-draft mixin: fasilitator revises an auto-generated education draft.

The every-3-days scheduler job DMs the fasilitator a copy-paste-ready group
education post and stores it as ``type='education'`` in ``content_drafts``.
The fasilitator can reply ``edit edukasi [instruksi]`` to regenerate it on the
same topic. There is no send/schedule step — education is never auto-broadcast.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_EDUCATION_EDIT_PATTERN = re.compile(
    r"\bedit\s+edukasi\b", re.IGNORECASE
)


class EducationDraftMixin:
    """Handle ``edit edukasi [instruksi]`` revisions of the latest draft."""

    @classmethod
    def _is_education_edit(cls, message: str) -> bool:
        return bool(message) and bool(_EDUCATION_EDIT_PATTERN.search(message))

    async def _handle_education_edit(self, message: str, context: dict) -> str:
        from backend.agents.education_generator import EducationContentGenerator
        from backend.infrastructure.composition_root import (
            build_content_draft_repository,
        )

        repo = build_content_draft_repository()
        try:
            draft = await repo.get_latest_draft("education")
        except Exception as exc:
            logger.warning("education draft lookup failed: %s", exc)
            return (
                "Gagal mengambil draft edukasi (apakah tabel `content_drafts` "
                "sudah ada?)."
            )
        if not draft:
            return "Tidak ada draft edukasi untuk direvisi."

        match = _EDUCATION_EDIT_PATTERN.search(message)
        guidance = message[match.end():].strip() or None
        topic = draft.get("topic") or ""

        generator = EducationContentGenerator()
        try:
            content = await generator.generate(topic, guidance=guidance)
        except Exception as exc:
            logger.warning("education regenerate failed: %s", exc)
            return "Gagal merevisi konten edukasi. Coba lagi."

        await repo.update(draft["id"], {"content": content})
        return generator.build_draft_message(topic, content)
