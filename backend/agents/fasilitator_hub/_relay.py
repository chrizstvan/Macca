"""Relay-save mixin: fasilitator saves a report on behalf of another volunteer."""

import logging
import re

logger = logging.getLogger(__name__)


class RelayMixin:
    """``save_report_for`` flow — parse 'Sari: 5kg Menteng', park pending, save."""

    # ------------------------------------------------------------------ #
    # Save report on behalf of another volunteer (fasilitator relay)      #
    # ------------------------------------------------------------------ #

    # ``5kg``, ``5 kg``, ``5.5 kg``, ``5,5 kg`` — capture the number.
    _RELAY_KG_PATTERN = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*kg\b", re.IGNORECASE
    )
    # ``Sari:`` prefix or ``untuk Sari`` / ``buat Sari`` connectives.
    _RELAY_TARGET_PATTERN = re.compile(
        r"^([A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+)?)\s*:|"
        r"\b(?:untuk|buat|atas\s+nama|dari)\s+([A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+)?)",
        re.IGNORECASE,
    )
    # Location after "di <place>" or "dari <place>" (skip when the latter
    # is the target connective above).
    _RELAY_LOCATION_PATTERN = re.compile(
        r"\bdi\s+([A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+)*)", re.IGNORECASE
    )
    _RELAY_SKIP_PHOTO_VOCAB = (
        "no photo", "tanpa foto", "no foto", "skip foto", "skip photo",
        "ga ada foto", "gak ada foto", "tidak ada foto", "engga ada foto",
        "lewati foto", "tanpa gambar",
    )
    _RELAY_CANCEL_VOCAB = ("batal", "cancel", "stop relay", "stop", "cancel relay")

    async def _handle_save_report_for(
        self, message: str, context: dict
    ) -> str:
        """Parse 'Sari: 5kg Menteng' style → SubmitReport for target volunteer.

        When a photo is already attached (image with caption that classified
        as ``save_report_for``), the report is saved immediately. Otherwise
        the parsed data is parked in pending state and the fasilitator is
        prompted to send the photo OR reply 'no photo' / 'tanpa foto'.
        """
        kg, target_name, location = self._relay_parse(message)
        if kg is None or target_name is None:
            return (
                "Format laporan tidak terbaca. Coba: `Sari: 5 kg Menteng` "
                "atau `catat 3 kg untuk Hendra di Cikini`."
            )

        target = await self._relay_resolve_volunteer(target_name)
        if target is None:
            return f"Volunteer '{target_name}' tidak ditemukan di database."
        if isinstance(target, list):
            names = ", ".join(t.get("name") or "?" for t in target)
            return (
                f"Ada beberapa volunteer cocok '{target_name}': {names}. "
                "Sebutkan nama lengkap."
            )

        # Photo already attached? Save now.
        photo_url = context.get("photo_url")
        if photo_url:
            return await self._relay_perform_save(
                target=target,
                kg=kg,
                location=location or (target.get("area") or "-"),
                photo_url=photo_url,
                context=context,
                require_photo=True,
            )

        # No photo yet → park pending state, ask for photo or 'no photo'.
        from backend.agents.services import pending_state as _pending_state

        _pending_state.set_pending(
            _pending_state.pending_key(context),
            "fasilitator_relay_waiting_photo",
            {
                "target_volunteer_id": str(target["id"]),
                "target_name": target.get("name") or "?",
                "target_area": target.get("area") or "-",
                "kg": kg,
                "location": location or (target.get("area") or "-"),
            },
        )
        return (
            f"📷 Kirim foto laporan {target.get('name')} "
            f"({kg:g} kg di {location or target.get('area') or '-'})?\n\n"
            "Kalau memang tidak ada foto, ketik *no photo* / *tanpa foto* "
            "dan laporan tetap disimpan (verified)."
        )

    async def _resume_relay_save(
        self, *, message: str, context: dict, entry: dict
    ) -> str:
        """Finish a parked relay-save: photo arrived OR 'no photo' typed."""
        from backend.agents.services import pending_state as _pending_state

        data = entry.get("data") or {}
        target_id = data.get("target_volunteer_id")
        target = (
            await self._relay_volunteer_by_id(target_id) if target_id else None
        )
        if target is None:
            _pending_state.store.pop(
                _pending_state.pending_key(context), None
            )
            return (
                "Volunteer untuk relay tidak ditemukan lagi. Mulai ulang dengan "
                "perintah laporan baru."
            )

        kg = float(data.get("kg") or 0)
        location = data.get("location") or target.get("area") or "-"

        photo_url = context.get("photo_url")
        lower = (message or "").strip().lower()
        is_skip = any(kw in lower for kw in self._RELAY_SKIP_PHOTO_VOCAB)
        is_cancel = lower in self._RELAY_CANCEL_VOCAB or any(
            lower.startswith(kw) for kw in self._RELAY_CANCEL_VOCAB
        )

        if is_cancel:
            _pending_state.store.pop(
                _pending_state.pending_key(context), None
            )
            return (
                f"❎ Relay laporan untuk {target.get('name', '?')} dibatalkan."
            )

        if not photo_url and not is_skip:
            # Stay in pending; nudge with the format reminder.
            return (
                "Masih menunggu foto laporan untuk "
                f"{target.get('name', '?')}.\n"
                "Ketik *no photo* / *tanpa foto* untuk simpan tanpa foto, "
                "atau *batal* untuk membatalkan."
            )

        _pending_state.store.pop(_pending_state.pending_key(context), None)
        return await self._relay_perform_save(
            target=target,
            kg=kg,
            location=location,
            photo_url=photo_url,
            context=context,
            require_photo=False if is_skip else True,
        )

    async def _relay_perform_save(
        self,
        *,
        target: dict,
        kg: float,
        location: str,
        photo_url: str | None,
        context: dict,
        require_photo: bool,
    ) -> str:
        """Call the SubmitReport use case as the relay source."""
        from uuid import UUID

        from backend.application.use_cases.submit_report import (
            DuplicateClarificationNeeded, NeedsPhoto, PhotoRejected, Saved,
        )
        from backend.domain.errors import InvalidKg
        from backend.infrastructure.composition_root import build_submit_report

        use_case = build_submit_report()
        try:
            outcome = await use_case.execute(
                volunteer_id=UUID(str(target["id"])),
                kg_value=kg,
                location=location,
                source="fasilitator_relay",
                photo_url=photo_url,
                is_test=bool(context.get("is_test_mode")),
                skip_duplicate_check=False,
                extra_data={"relayed_by": "fasilitator_hub"},
                require_photo=require_photo,
            )
        except InvalidKg as exc:
            return f"Gagal simpan laporan: {exc}"

        name = target.get("name") or "?"
        if isinstance(outcome, NeedsPhoto):
            # Should not happen — caller guards. Keep as safety net.
            return outcome.message
        if isinstance(outcome, PhotoRejected):
            return (
                f"❌ Foto untuk {name} ditolak verifier ({outcome.reason}). "
                "Kirim ulang foto plastik + timbangan."
            )
        if isinstance(outcome, DuplicateClarificationNeeded):
            existing_kg = outcome.existing.kg_collected.value
            return (
                f"⚠️ {name} sudah punya laporan {existing_kg:g} kg hari ini. "
                "Untuk simpan tetap, ulangi perintah dengan kata 'tambahan' "
                "di akhir, atau abaikan."
            )
        assert isinstance(outcome, Saved)
        report = outcome.report
        total = outcome.total_kg
        skip_label = "" if photo_url else " (tanpa foto — verified)"
        return (
            f"✅ Laporan {name} tersimpan{skip_label}.\n"
            f"📦 {report.kg_collected.value:g} kg di {report.location}\n"
            f"Progress total {name}: {total:g} kg"
        )

    # ------------------------------------------------------------------ #
    # Relay helpers                                                       #
    # ------------------------------------------------------------------ #

    @classmethod
    def _relay_parse(cls, message: str) -> tuple[float | None, str | None, str | None]:
        """Extract (kg, target_name, location) from a free-form relay message."""
        if not message:
            return None, None, None
        # kg
        kg_match = cls._RELAY_KG_PATTERN.search(message)
        kg = (
            float(kg_match.group(1).replace(",", "."))
            if kg_match
            else None
        )
        # target name — prefer prefix "Name:" then "untuk Name" etc.
        target = None
        t_match = cls._RELAY_TARGET_PATTERN.search(message)
        if t_match:
            target = (t_match.group(1) or t_match.group(2) or "").strip()
        # location — "di <place>"
        location = None
        l_match = cls._RELAY_LOCATION_PATTERN.search(message)
        if l_match:
            location = l_match.group(1).strip()
        return kg, target, location

    async def _relay_resolve_volunteer(
        self, name: str
    ) -> dict | list[dict] | None:
        """ilike + exact-match resolver. Returns single dict, list (ambiguous), or None."""
        if not name:
            return None
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        rows = await build_volunteer_query_repository().find_by_name(name)
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]
        # Exact case-insensitive match wins.
        exact = [r for r in rows if (r.get("name") or "").lower() == name.lower()]
        if len(exact) == 1:
            return exact[0]
        return rows

    @staticmethod
    async def _relay_volunteer_by_id(volunteer_id: str | None) -> dict | None:
        if not volunteer_id:
            return None
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        return await build_volunteer_query_repository().get_by_id(volunteer_id)
