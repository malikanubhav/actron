"""Fake Jev (TypeSafe System One) server as an `httpx.MockTransport`.

It checks the request the way the real API documents (Bearer auth, `model`, `state`, typed `questions`)
and answers in the documented response shape (`answers[id].type/noul/choice/score/probabilities/
confidence/legend`, `usage`). Tests script status codes and answers.

Usage:
    fake = FakeJev(statuses=[429, 429], noul=0.8)
    jev.set_transport(fake.transport())
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

import httpx

AnswerFn = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
# (question id, question, state) -> raw answer (without "type", which is added)


def noul_answer(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": p}


def choice_answer(choice: str, options: list[str], p: float = 0.8) -> dict[str, Any]:
    rest = [o for o in options if o != choice]
    share = (1.0 - p) / len(rest) if rest else 0.0
    probs = {o: (p if o == choice else share) for o in options}
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": probs,
        "confidence": round(p * 0.9, 3),
    }


def score_answer(levels: list[str], score: float) -> dict[str, Any]:
    lo = math.floor(score)
    hi = min(lo + 1, len(levels) - 1)
    frac = score - lo
    probs = {str(i): 0.0 for i in range(len(levels))}
    probs[str(lo)] += 1.0 - frac
    probs[str(hi)] += frac
    return {
        "type": "score",
        "score": score,
        "legend": {str(i): lvl for i, lvl in enumerate(levels)},
        "probabilities": probs,
        "confidence": 0.7,
    }


class FakeJev:
    def __init__(
        self,
        *,
        statuses: list[int] | None = None,
        noul: float | Callable[[str, dict[str, Any], dict[str, Any]], float] = 0.5,
        choice: str | Callable[[str, dict[str, Any], dict[str, Any]], str] | None = None,
        score: float = 1.0,
        answer_fn: AnswerFn | None = None,
        retry_after: str | None = None,
        malformed: bool = False,
        model: str = "jev-1.13.0",
    ) -> None:
        self.statuses = list(statuses or [])
        self.noul = noul
        self.choice = choice
        self.score = score
        self.answer_fn = answer_fn
        self.retry_after = retry_after
        self.malformed = malformed
        self.model = model
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _error(self, status: int, message: str) -> httpx.Response:
        headers = (
            {"retry-after": self.retry_after} if self.retry_after and status in (429, 529) else {}
        )
        return httpx.Response(status, json={"error": {"message": message}}, headers=headers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            body = None
        self.requests.append(body if isinstance(body, dict) else {})
        self.headers.append(dict(request.headers))
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return self._error(status, f"scripted {status}")
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or len(auth) <= len("Bearer "):
            return self._error(401, "Missing or invalid API key")
        if not isinstance(body, dict):
            return self._error(400, "Body is not valid JSON")
        for name in ("model", "state", "questions"):
            if name not in body:
                return self._error(422, f"missing field {name}")
        questions = body["questions"]
        if not isinstance(questions, dict) or not questions:
            return self._error(422, "questions must be a non-empty map")
        answers: dict[str, Any] = {}
        for qid, q in questions.items():
            kind = q.get("type") if isinstance(q, dict) else None
            if kind not in ("noul", "choice", "score") or "instructions" not in q:
                return self._error(422, f"questions.{qid}: malformed question")
            if kind == "choice" and not isinstance(q.get("criteria"), dict):
                return self._error(422, f"questions.{qid}.criteria must be a map")
            if kind == "score":
                levels = q.get("criteria")
                if not isinstance(levels, list) or not 2 <= len(levels) <= 10:
                    return self._error(422, f"questions.{qid}.criteria must list 2 to 10 levels")
            answers[qid] = self._answer(qid, q, body["state"])
        if self.malformed:
            answers = {qid: {"type": a["type"]} for qid, a in answers.items()}
        size = len(json.dumps(body))
        return httpx.Response(
            200,
            json={
                "model": self.model,
                "answers": answers,
                "usage": {"input_tokens": max(1, size // 4), "output_tokens": 10 * len(answers)},
            },
        )

    def _answer(self, qid: str, q: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if self.answer_fn is not None:
            raw = dict(self.answer_fn(qid, q, state))
            raw.setdefault("type", q["type"])
            return raw
        if q["type"] == "noul":
            p = self.noul(qid, q, state) if callable(self.noul) else self.noul
            return noul_answer(p)
        if q["type"] == "choice":
            options = list(q["criteria"])
            pick = self.choice(qid, q, state) if callable(self.choice) else self.choice
            return choice_answer(pick if pick in options else options[0], options)
        return score_answer(list(q["criteria"]), min(self.score, len(q["criteria"]) - 1))


class SleepRecorder:
    """Replaces asyncio.sleep in the Jev client so backoff tests run instantly."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
