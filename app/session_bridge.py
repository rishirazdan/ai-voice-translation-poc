from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal
from uuid import uuid4

from fastapi import WebSocket

Leg = Literal["caller", "agent", "unknown"]


@dataclass(frozen=True)
class BridgeParticipant:
    participant_id: str
    session_id: str
    leg: Leg
    call_sid: str | None
    websocket: WebSocket


class BridgeSessionRegistry:
    def __init__(self) -> None:
        self._by_session: dict[str, dict[str, BridgeParticipant]] = {}
        self._pending_by_session: dict[str, dict[Leg, list[dict[str, Any]]]] = {}

    def register(
        self,
        session_id: str,
        leg: str,
        call_sid: str | None,
        websocket: WebSocket,
    ) -> BridgeParticipant:
        normalized_leg: Leg
        if leg in {"caller", "agent"}:
            normalized_leg = leg
        else:
            normalized_leg = "unknown"

        participant = BridgeParticipant(
            participant_id=uuid4().hex,
            session_id=session_id,
            leg=normalized_leg,
            call_sid=call_sid,
            websocket=websocket,
        )
        self._by_session.setdefault(session_id, {})[participant.participant_id] = participant
        return participant

    def unregister(self, participant: BridgeParticipant) -> None:
        participants = self._by_session.get(participant.session_id)
        if not participants:
            return
        participants.pop(participant.participant_id, None)
        if not participants:
            self._by_session.pop(participant.session_id, None)
            self._pending_by_session.pop(participant.session_id, None)

    def active_session_count(self) -> int:
        return len(self._by_session)

    def participant_count(self, session_id: str) -> int:
        participants = self._by_session.get(session_id, {})
        return len(participants)

    def get_counterpart(self, participant: BridgeParticipant) -> BridgeParticipant | None:
        if participant.leg == "unknown":
            return None
        desired_leg: Leg = "agent" if participant.leg == "caller" else "caller"
        participants = self._by_session.get(participant.session_id, {})
        for peer in participants.values():
            if peer.participant_id != participant.participant_id and peer.leg == desired_leg:
                return peer
        return None

    def enqueue_pending(self, session_id: str, target_leg: Leg, message: dict[str, Any]) -> None:
        if target_leg not in {"caller", "agent"}:
            return
        per_session = self._pending_by_session.setdefault(session_id, {"caller": [], "agent": [], "unknown": []})
        per_session[target_leg].append(message)

    def dequeue_pending(self, session_id: str, leg: Leg) -> list[dict[str, Any]]:
        per_session = self._pending_by_session.get(session_id)
        if not per_session:
            return []
        queued = per_session.get(leg, [])
        per_session[leg] = []
        if not per_session.get("caller") and not per_session.get("agent"):
            self._pending_by_session.pop(session_id, None)
        return queued
