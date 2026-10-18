"""Block Kit builders for the Slack messages (PROMPT 8.9, spec C9, PRD 13.10).

Every builder takes the RequestDetail dict (spec B, B.C7) and returns a message payload
(`text` plus `blocks` or `attachments`) ready for chat.postMessage / chat.update.
State names, text and colours come from one JSON map shared with the UI (C-AC-10).
No emoji as status and no exclamation marks in our own copy (C-AC-36).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from actron.config import REPO_ROOT
from actron.integrations.slack_common import parse_time, request_url

Message = dict[str, Any]
Block = dict[str, Any]

BACKEND_STATES = REPO_ROOT / "backend" / "actron" / "flow" / "states.json"
FRONTEND_STATES = REPO_ROOT / "frontend" / "lib" / "states.json"

EVIDENCE_LIMIT = 3
QUOTE_LIMIT = 600
BUTTON_ANSWER_MAX = 5
FINDINGS_STATES = ("Needs your input", "Ticket ready", "Awaiting approval")

# ---------------------------------------------------------------- state map


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = (
        isinstance(data, dict)
        and isinstance(data.get("requestStates"), dict)
        and isinstance(data.get("tones"), dict)
    )
    return dict(data) if ok else None


@lru_cache(maxsize=1)
def state_map() -> dict[str, Any]:
    """Request states and tones from backend/actron/flow/states.json (W6), else frontend/lib/states.json.

    W6's file names the chip text `slackLabel` and has no `labels`; both are accepted, and the label
    names fall back to the frontend file."""
    front = _load(FRONTEND_STATES)
    primary = _load(BACKEND_STATES) or front
    if primary is None:
        raise FileNotFoundError("no states.json with requestStates and tones was found")
    states = {
        name: {**entry, "text": entry.get("text") or entry.get("slackLabel") or name.upper()}
        for name, entry in primary["requestStates"].items()
    }
    labels = primary.get("labels") or (front or {}).get("labels") or {}
    return {"requestStates": states, "tones": primary["tones"], "labels": labels}


def state_text(state: str) -> str:
    entry = state_map()["requestStates"].get(state)
    return str(entry["text"]) if entry else state.upper()


def state_color(state: str) -> str:
    m = state_map()
    entry = m["requestStates"].get(state)
    tone = entry["tone"] if entry else "idle"
    return str(m["tones"][tone]["hex"])


def label_text(label: str | None) -> str | None:
    if not label:
        return None
    entry = state_map()["labels"].get(label)
    return str(entry["text"]) if entry else label.replace("_", " ").upper()


# ---------------------------------------------------------------- text helpers


def esc(text: str) -> str:
    """Slack mrkdwn escaping for text we did not write."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str | None, label: str) -> str:
    safe = esc(label).replace("|", "/")
    if not url:
        return safe
    return f"<{url.replace('>', '%3E').replace('|', '%7C')}|{safe}>"


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + "…"


def one_line(text: str, limit: int = 200) -> str:
    return clip(re.sub(r"\s+", " ", text), limit)


def sentence(text: str) -> str:
    text = one_line(text).rstrip()
    return text if not text or text[-1] in ".?" else text + "."


def short_id(request_id: str) -> str:
    return request_id.removeprefix("req_")[-8:].upper()


def elapsed_text(start: datetime | None, end: datetime) -> str:
    if start is None:
        return "0s"
    secs = max(int((end - start).total_seconds()), 0)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def _elapsed(view: dict[str, Any], now: datetime) -> str:
    state_info = state_map()["requestStates"].get(view.get("state", ""), {})
    start = parse_time(view.get("createdAt"))
    end = (parse_time(view.get("updatedAt")) or now) if state_info.get("final") else now
    return elapsed_text(start, end)


# ---------------------------------------------------------------- block pieces


def header(title: str) -> Block:
    return {"type": "header", "text": {"type": "plain_text", "text": clip(title or "Request", 150)}}


def section(text: str) -> Block:
    return {"type": "section", "text": {"type": "mrkdwn", "text": clip(text, 3000)}}


def context(*texts: str) -> Block:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": clip(t, 3000)} for t in texts],
    }


def button(
    label: str,
    action_id: str,
    *,
    value: str | None = None,
    url: str | None = None,
    style: str | None = None,
    confirm: Block | None = None,
) -> Block:
    b: Block = {"type": "button", "text": {"type": "plain_text", "text": clip(label, 75)}}
    if url:
        b["url"] = url
        # URL buttons still need an action id so Slack does not complain; the bot acks "open:" ids.
    b["action_id"] = action_id
    if value is not None:
        b["value"] = value
    if style:
        b["style"] = style
    if confirm:
        b["confirm"] = confirm
    return b


def confirm_dialog(title: str, text: str, confirm: str, deny: str = "Cancel") -> Block:
    return {
        "title": {"type": "plain_text", "text": clip(title, 100)},
        "text": {"type": "plain_text", "text": clip(text, 300)},
        "confirm": {"type": "plain_text", "text": clip(confirm, 30)},
        "deny": {"type": "plain_text", "text": clip(deny, 30)},
    }


def actions(block_id: str, elements: list[Block]) -> Block:
    return {"type": "actions", "block_id": block_id, "elements": elements}


def open_button(view: dict[str, Any], label: str = "Open in Actron") -> Block:
    return button(label, f"open:{view['id']}", url=request_url(view["id"]))


def _allowed(view: dict[str, Any], action: str) -> bool:
    allowed = view.get("allowedActions")
    return True if allowed is None else action in allowed


def _revision_n(view: dict[str, Any]) -> int | None:
    cur = view.get("currentRevision")
    return int(cur["n"]) if cur else None


def _pr_label(pr: dict[str, Any]) -> str:
    return f"Approve PR #{pr['number']} (head {str(pr['headSha'])[:7]})"


def approve_pr_button(view: dict[str, Any]) -> Block:
    pr = view["pr"]
    sha7 = str(pr["headSha"])[:7]
    return button(
        _pr_label(pr),
        f"approve_pr:{view['id']}:{pr['headSha']}",
        style="primary",
        confirm=confirm_dialog(
            "Approve this pull request",
            f"You are approving PR #{pr['number']} at head {sha7}. If the branch moves, the approval is refused.",
            "Approve",
        ),
    )


def _latest_build(view: dict[str, Any]) -> dict[str, Any] | None:
    builds = view.get("builds") or []
    return builds[-1] if builds else None


def tests_sentence(view: dict[str, Any]) -> str | None:
    build = _latest_build(view)
    if not build:
        return None
    passed, failed = int(build.get("testsPassed", 0)), int(build.get("testsFailed", 0))
    total = passed + failed
    return f"{passed} of {total} tests passed." if total else None


# ---------------------------------------------------------------- evidence


_ROLE_RANK = {"conflict": 0, "constraint": 1, "impact": 2, "similar_work": 3, "owner": 4, "test": 5}


def pick_evidence(view: dict[str, Any]) -> list[dict[str, Any]]:
    ev = list(view.get("evidence") or [])
    ev.sort(key=lambda e: (_ROLE_RANK.get(e.get("role", ""), 9), -float(e.get("confidence", 0))))
    return ev[:EVIDENCE_LIMIT]


_SOURCE_LABELS = {
    "slack_message": "Slack message",
    "github_pr": "GitHub PR",
    "github_issue": "GitHub issue",
    "github_review_comment": "GitHub review",
    "linear_issue": "Linear issue",
    "linear_comment": "Linear comment",
    "commit": "Commit",
    "code": "Code",
}


def source_label(kind: Any) -> str:
    kind = str(kind or "source")
    return str(_SOURCE_LABELS.get(kind, kind.replace("_", " ").capitalize()))


def evidence_blocks(view: dict[str, Any]) -> list[Block]:
    blocks: list[Block] = []
    for e in pick_evidence(view):
        quote = (e.get("quote") or e.get("title") or "").strip()
        quote = clip(quote, QUOTE_LIMIT)
        body = "\n".join(
            f"> {esc(line)}" if line.strip() else ">" for line in quote.splitlines() or [""]
        )
        src = e.get("source") or {}
        label = source_label(src.get("type") or e.get("nodeType"))
        who = src.get("author")
        meta = link(src.get("url"), label) + (f" · {esc(str(who))}" if who else "")
        blocks.append(section(body))
        blocks.append(context(meta))
    return blocks


# ---------------------------------------------------------------- questions


def pending_questions(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [q for q in view.get("questions") or [] if not q.get("answer")]


def answer_action_id(
    request_id: str, question_id: str, value: str, index: int | None = None
) -> str:
    aid = f"answer:{request_id}:{question_id}:{value}"
    if len(aid) <= 255 or index is None:
        return aid[:255]
    return f"answer:{request_id}:{question_id}:#{index}"


def answer_controls(view: dict[str, Any], q: dict[str, Any]) -> list[Block]:
    """Buttons for up to five options, a menu for more, nothing for text questions."""
    options = q.get("options") or []
    if q.get("kind") == "text" or not options:
        return []
    rid, qid = view["id"], q["questionId"]
    if len(options) <= BUTTON_ANSWER_MAX:
        return [
            actions(
                f"answers_{qid}"[:255],
                [
                    button(
                        str(o.get("label") or o["value"]),
                        answer_action_id(rid, qid, str(o["value"]), i),
                        value=str(o["value"])[:2000],
                        style="primary" if o.get("preselected") else None,
                    )
                    for i, o in enumerate(options)
                ],
            )
        ]
    return [
        actions(
            f"answers_{qid}"[:255],
            [
                {
                    "type": "static_select",
                    "action_id": f"answer:{rid}:{qid}:~select"[:255],
                    "placeholder": {"type": "plain_text", "text": "Choose an answer"},
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": clip(str(o.get("label") or o["value"]), 75),
                            },
                            "value": str(o["value"])[:150],
                        }
                        for o in options[:100]
                    ],
                }
            ],
        )
    ]


def _question_text(q: dict[str, Any], index: int, total: int) -> str:
    text = f"*Question {index} of {total}.* {esc(q['text'])}"
    notes = [
        f"{esc(str(o['label']))}: {esc(str(o['note']))}"
        for o in q.get("options") or []
        if o.get("note")
    ]
    if notes:
        text += "\n" + "\n".join(notes)
    if q.get("kind") == "text":
        text += f"\nReply in this thread starting with {index}."
    return text


def question_message(
    view: dict[str, Any], q: dict[str, Any], index: int, total: int, mention: str | None = None
) -> Message:
    lead = f"<@{mention}> " if mention else ""
    blocks = [section(lead + _question_text(q, index, total)), *answer_controls(view, q)]
    blocks.append(actions(f"open_{q['questionId']}"[:255], [open_button(view)]))
    return {"text": f"Question {index} of {total}: {one_line(q['text'], 150)}", "blocks": blocks}


def question_answered_message(
    view: dict[str, Any], q: dict[str, Any], index: int, total: int
) -> Message:
    ans = q.get("answer") or {}
    by = (ans.get("by") or {}).get("name")
    label = next(
        (str(o.get("label")) for o in q.get("options") or [] if o.get("value") == ans.get("value")),
        str(ans.get("value", "")),
    )
    said = f"Answered: {esc(label)}" + (f" by {esc(str(by))}" if by else "") + "."
    return {
        "text": f"Question {index} of {total} answered.",
        "blocks": [section(f"*Question {index} of {total}.* {esc(q['text'])}\n{said}")],
    }


# ---------------------------------------------------------------- main messages


def _approval_line(view: dict[str, Any]) -> str | None:
    """'Approved by <name> in Slack.' from the latest accepted approval (kept visible after the button goes)."""
    state = view.get("state")
    kind = "ticket" if state == "Building" else "pr" if state == "Done" else None
    if kind is None:
        return None
    for a in reversed(view.get("approvals") or []):
        if a.get("kind") == kind and a.get("status") == "accepted":
            return approval_text(kind, (a.get("by") or {}).get("name"), a.get("surface"))
    return None


def approval_text(kind: str, name: str | None, surface: str | None) -> str:
    where = "Slack" if surface == "slack" else "Actron"
    who = esc(name) if name else "a teammate"
    tail = " Build started." if kind == "ticket" else ""
    return f"Approved by {who} in {where}.{tail}"


def _status_actions(view: dict[str, Any]) -> list[Block]:
    state, rid = view["state"], view["id"]
    els: list[Block] = []
    if state == "Needs your input":
        pend = pending_questions(view)
        if pend:
            return [*answer_controls(view, pend[0]), actions("status_actions", [open_button(view)])]
    if (
        state == "Awaiting approval"
        and _allowed(view, "approve_ticket")
        and view.get("currentRevision")
    ):
        cur = view["currentRevision"]
        els.append(
            button(
                f"Approve ticket v{cur['n']}",
                f"approve_ticket:{rid}:{cur['hash']}",
                style="primary",
            )
        )
    if state == "PR ready for review" and view.get("pr"):
        if _allowed(view, "approve_pr"):
            els.append(approve_pr_button(view))
        if _allowed(view, "pr_feedback"):
            els.append(button("Request changes", f"request_changes:{rid}"))
        if _allowed(view, "close_pr"):
            els.append(
                button(
                    "Close PR",
                    f"close_pr:{rid}",
                    confirm=confirm_dialog(
                        "Close this pull request",
                        "The PR is closed on GitHub and the request is cancelled.",
                        "Close PR",
                    ),
                )
            )
    if state == "Needs attention" and _allowed(view, "retry"):
        els.append(button("Retry", f"retry:{rid}"))
    els.append(
        open_button(
            view, "Review in Actron" if state == "PR ready for review" else "Open in Actron"
        )
    )
    if state == "PR ready for review" and view.get("pr", {}).get("url"):
        els.append(button("Open PR", f"open:{rid}:pr", url=view["pr"]["url"]))
    return [actions("status_actions", els)]


def status_message(view: dict[str, Any], *, now: datetime | None = None) -> Message:
    """The one status message per request, edited in place (PROMPT 8.9)."""
    from actron.integrations.slack_common import now_utc

    now = now or now_utc()
    state = view["state"]
    blocks: list[Block] = [
        header(view.get("title", "")),
        context(f"STATE · {state_text(state)} · {_elapsed(view, now)}"),
        section(esc(view.get("headline") or state)),
    ]
    label = label_text(view.get("label"))
    if state in FINDINGS_STATES:
        if label:
            blocks.append(context(f"LABEL · {label}"))
        blocks.extend(evidence_blocks(view))
    banner = _approval_line(view)
    if banner:
        blocks.append(context(banner))
    if state == "Needs your input":
        pend = pending_questions(view)
        if pend:
            idx = [q["questionId"] for q in view.get("questions") or []].index(
                pend[0]["questionId"]
            ) + 1
            blocks.append(section(_question_text(pend[0], idx, len(view["questions"]))))
    if state == "Done" and view.get("answer"):
        blocks.append(section(esc(view["answer"]["text"])))
    blocks.extend(_status_actions(view))
    fallback = f"{view.get('title', 'Request')}: {view.get('headline') or state}"
    return {
        "text": clip(fallback, 300),
        "attachments": [
            {"color": state_color(state), "fallback": clip(fallback, 300), "blocks": blocks}
        ],
    }


def acknowledgement(view: dict[str, Any]) -> Message:
    """Posted within seconds of the request; later replaced by the status message."""
    state = view.get("state", "Investigating")
    blocks = [
        section("On it. Investigating your request."),
        context(f"REQUEST {short_id(view['id'])} · {state_text(state)}"),
        actions("ack_actions", [open_button(view)]),
    ]
    return {"text": "On it. Investigating your request.", "blocks": blocks}


def approval_confirmation(
    view: dict[str, Any],
    approver: str | None,
    kind: str = "ticket",
    surface: str = "slack",
    *,
    now: datetime | None = None,
) -> Message:
    """Status message right after an approval: the approve button is gone."""
    from actron.integrations.slack_common import now_utc

    now = now or now_utc()
    state = view["state"]
    text = approval_text(kind, approver, surface)
    blocks = [
        header(view.get("title", "")),
        context(f"STATE · {state_text(state)} · {_elapsed(view, now)}"),
        section(text),
        actions("status_actions", [open_button(view)]),
    ]
    return {
        "text": text,
        "attachments": [{"color": state_color(state), "fallback": text, "blocks": blocks}],
    }


def needs_you_sentence(view: dict[str, Any], kind: str) -> str:
    title = one_line(view.get("title", "your request"), 80)
    if kind == "needs_input":
        n = len(pending_questions(view)) or 1
        return f"{n} question{'s' if n != 1 else ''} need{'s' if n == 1 else ''} your answer on {title}."
    if kind == "ticket":
        cur = view.get("currentRevision")
        v = f" v{cur['n']}" if cur else ""
        return f"Ticket{v} for {title} is ready for your approval."
    if kind == "pr":
        pr = view.get("pr")
        num = f" #{pr['number']}" if pr else ""
        return f"PR{num} for {title} is ready for your review."
    return f"{title} needs your attention."


def needs_you_dm(view: dict[str, Any], kind: str, *, thread_url: str | None = None) -> Message:
    """One sentence and a link to the thread. Sent only to the person who must act."""
    text = needs_you_sentence(view, kind)
    target = thread_url or request_url(view["id"])
    label = "Open the thread" if thread_url else "Open in Actron"
    return {"text": text, "blocks": [section(f"{esc(text)} {link(target, label)}")]}


def needs_you_thread(view: dict[str, Any], kind: str, mention: str | None) -> Message:
    lead = f"<@{mention}> " if mention else ""
    text = needs_you_sentence(view, kind)
    return {
        "text": text,
        "blocks": [section(f"{lead}{esc(text)}"), actions("thread_actions", [open_button(view)])],
    }


def build_finished(view: dict[str, Any]) -> Message:
    pr = view.get("pr") or {}
    tests = tests_sentence(view)
    text = f"PR #{pr.get('number', '')} is ready for review." + (f" {tests}" if tests else "")
    els: list[Block] = []
    if pr and _allowed(view, "approve_pr"):
        els.append(approve_pr_button(view))
    if _allowed(view, "pr_feedback"):
        els.append(button("Request changes", f"request_changes:{view['id']}"))
    els.append(open_button(view, "Review in Actron"))
    if pr.get("url"):
        els.append(button("Open PR", f"open:{view['id']}:pr", url=pr["url"]))
    return {"text": text, "blocks": [section(esc(text)), actions("build_finished_actions", els)]}


_STOP_REASONS = {
    "scope_change": "The change needs more than the approved ticket covers",
    "tests_weakened": "The change would have weakened existing tests",
    "timeout": "The build ran out of time",
    "missing_fork": "No fork is set up to push to",
    "missing_branch": "The target branch could not be found",
    "missing_identity": "The bot identity is not configured",
    "memory_stale": "Actron's memory is not up to date with the merged code",
}


def failure(view: dict[str, Any]) -> Message:
    build = _latest_build(view)
    reason_code = (build or {}).get("stopReason")
    reason = _STOP_REASONS.get(str(reason_code), "") if reason_code else ""
    if not reason and reason_code:
        reason = str(reason_code).replace("_", " ").capitalize()
    if not reason:
        last = view.get("lastEvent") or {}
        reason = last.get("sentence", "")
    if build:
        n = int(build.get("attempts", 0))
        lead = (
            "The build failed twice"
            if n == 2
            else f"The build failed after {n} attempts"
            if n > 2
            else "The build failed"
        )
    else:
        lead = "The investigation did not finish"
    text = f"{lead}. {sentence(reason)}" if reason else f"{lead}."
    els: list[Block] = []
    if _allowed(view, "retry"):
        els.append(button("Retry", f"retry:{view['id']}"))
    els.append(open_button(view))
    return {"text": text, "blocks": [section(esc(text)), actions("failure_actions", els)]}


def answer_message(view: dict[str, Any]) -> Message:
    """Q&A answer posted in the thread: the answer, then each citation as a quote with its source."""
    ans = view.get("answer") or {"text": "", "citations": []}
    blocks: list[Block] = [section(esc(ans["text"]))]
    for c in ans.get("citations", [])[:5]:
        src = c.get("source") or {}
        quote = clip((c.get("quote") or c.get("title") or ""), QUOTE_LIMIT)
        blocks.append(section("\n".join(f"> {esc(x)}" for x in quote.splitlines() or [""])))
        who = src.get("author")
        blocks.append(
            context(
                link(src.get("url"), source_label(src.get("type")))
                + (f" · {esc(str(who))}" if who else "")
            )
        )
    blocks.append(actions("answer_actions", [open_button(view)]))
    return {"text": clip(ans["text"] or "Answer ready.", 300), "blocks": blocks}


def request_changes_modal(request_id: str, *, pr_number: int | None = None) -> dict[str, Any]:
    prompt = f"What should change in PR #{pr_number}?" if pr_number else "What should change?"
    return {
        "type": "modal",
        "callback_id": "request_changes",
        "private_metadata": request_id,
        "title": {"type": "plain_text", "text": "Request changes"},
        "submit": {"type": "plain_text", "text": "Send feedback"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "feedback",
                "label": {"type": "plain_text", "text": prompt},
                "element": {"type": "plain_text_input", "action_id": "text", "multiline": True},
            }
        ],
    }


_REFUSALS = {
    "stale_revision": "The ticket changed after this message. Open Actron to see the latest version and approve it there.",
    "stale_head": "The pull request has new commits since this message. Open Actron to review the latest head.",
    "external_edit": "The ticket was edited in Linear. Open Actron to review the change before approving.",
    "invalid_transition": "This request has moved on, so that action no longer applies.",
    "not_an_approver": "Only the requester, the workspace owner or a listed approver can approve this.",
}


def refusal_text(reason: str | None) -> str:
    return _REFUSALS.get(
        reason or "", "Actron could not apply that. Open the request in Actron for details."
    )


USAGE_TEXT = "Tell Actron what you need after the command. Example: /actron add a retry to the invoice export."


# ---------------------------------------------------------------- validation and lint

LIMITS = {
    "blocks_message": 50,
    "blocks_modal": 100,
    "header": 150,
    "section": 3000,
    "section_fields": 10,
    "field": 2000,
    "context_elements": 10,
    "context_text": 3000,
    "actions": 25,
    "button_text": 75,
    "action_id": 255,
    "block_id": 255,
    "button_value": 2000,
    "url": 3000,
    "confirm_title": 100,
    "confirm_text": 300,
    "confirm_button": 30,
    "option_text": 75,
    "options": 100,
    "modal_title": 24,
}


def _text_obj(errors: list[str], where: str, obj: Any, limit: int, kinds: tuple[str, ...]) -> None:
    if not isinstance(obj, dict) or obj.get("type") not in kinds:
        errors.append(f"{where}: text object must be one of {kinds}")
        return
    text = obj.get("text")
    if not isinstance(text, str) or not text:
        errors.append(f"{where}: text is empty")
    elif len(text) > limit:
        errors.append(f"{where}: text is {len(text)} characters, limit {limit}")


def _element(errors: list[str], where: str, el: dict[str, Any]) -> None:
    t = el.get("type")
    if t == "button":
        _text_obj(errors, f"{where}.text", el.get("text"), LIMITS["button_text"], ("plain_text",))
        aid = el.get("action_id", "")
        if not aid or len(aid) > LIMITS["action_id"]:
            errors.append(f"{where}: action_id missing or over {LIMITS['action_id']}")
        if len(el.get("value", "")) > LIMITS["button_value"]:
            errors.append(f"{where}: value over {LIMITS['button_value']}")
        if len(el.get("url", "")) > LIMITS["url"]:
            errors.append(f"{where}: url over {LIMITS['url']}")
        if el.get("style") not in (None, "primary", "danger"):
            errors.append(f"{where}: bad style")
        c = el.get("confirm")
        if c:
            _text_obj(
                errors,
                f"{where}.confirm.title",
                c.get("title"),
                LIMITS["confirm_title"],
                ("plain_text",),
            )
            _text_obj(
                errors,
                f"{where}.confirm.text",
                c.get("text"),
                LIMITS["confirm_text"],
                ("plain_text", "mrkdwn"),
            )
            _text_obj(
                errors,
                f"{where}.confirm.confirm",
                c.get("confirm"),
                LIMITS["confirm_button"],
                ("plain_text",),
            )
            _text_obj(
                errors,
                f"{where}.confirm.deny",
                c.get("deny"),
                LIMITS["confirm_button"],
                ("plain_text",),
            )
    elif t == "static_select":
        if not el.get("action_id") or len(el["action_id"]) > LIMITS["action_id"]:
            errors.append(f"{where}: action_id missing or too long")
        opts = el.get("options") or []
        if not 1 <= len(opts) <= LIMITS["options"]:
            errors.append(f"{where}: options must be 1 to {LIMITS['options']}")
        for i, o in enumerate(opts):
            _text_obj(
                errors,
                f"{where}.options[{i}]",
                o.get("text"),
                LIMITS["option_text"],
                ("plain_text",),
            )
            if not o.get("value") or len(o["value"]) > 150:
                errors.append(f"{where}.options[{i}]: value missing or over 150")
    elif t == "plain_text_input":
        if not el.get("action_id"):
            errors.append(f"{where}: action_id missing")
    else:
        errors.append(f"{where}: unsupported element type {t!r}")


def _block(errors: list[str], where: str, b: dict[str, Any]) -> None:
    t = b.get("type")
    if len(b.get("block_id", "")) > LIMITS["block_id"]:
        errors.append(f"{where}: block_id too long")
    if t == "header":
        _text_obj(errors, where, b.get("text"), LIMITS["header"], ("plain_text",))
    elif t == "section":
        if "text" not in b and not b.get("fields"):
            errors.append(f"{where}: section needs text or fields")
        if "text" in b:
            _text_obj(errors, where, b["text"], LIMITS["section"], ("mrkdwn", "plain_text"))
        fields = b.get("fields") or []
        if len(fields) > LIMITS["section_fields"]:
            errors.append(f"{where}: more than {LIMITS['section_fields']} fields")
        for f in fields:
            _text_obj(errors, f"{where}.field", f, LIMITS["field"], ("mrkdwn", "plain_text"))
    elif t == "context":
        els = b.get("elements") or []
        if not 1 <= len(els) <= LIMITS["context_elements"]:
            errors.append(f"{where}: context needs 1 to {LIMITS['context_elements']} elements")
        for e in els:
            _text_obj(
                errors, f"{where}.element", e, LIMITS["context_text"], ("mrkdwn", "plain_text")
            )
    elif t == "actions":
        els = b.get("elements") or []
        if not 1 <= len(els) <= LIMITS["actions"]:
            errors.append(f"{where}: actions needs 1 to {LIMITS['actions']} elements")
        ids = [e.get("action_id") for e in els]
        if len(set(ids)) != len(ids):
            errors.append(f"{where}: duplicate action_id in one actions block")
        for i, e in enumerate(els):
            _element(errors, f"{where}.elements[{i}]", e)
    elif t == "input":
        _text_obj(errors, f"{where}.label", b.get("label"), 2000, ("plain_text",))
        _element(errors, f"{where}.element", b.get("element") or {})
    elif t == "divider":
        pass
    else:
        errors.append(f"{where}: unsupported block type {t!r}")


def validate_blocks(blocks: list[dict[str, Any]], *, modal: bool = False) -> list[str]:
    errors: list[str] = []
    cap = LIMITS["blocks_modal"] if modal else LIMITS["blocks_message"]
    if len(blocks) > cap:
        errors.append(f"{len(blocks)} blocks, limit {cap}")
    for i, b in enumerate(blocks):
        _block(errors, f"blocks[{i}]", b)
    return errors


def validate_message(msg: Message) -> list[str]:
    """Slack's Block Kit size limits for a chat.postMessage payload (C-AC-35). Empty list means valid."""
    errors: list[str] = []
    if not msg.get("text"):
        errors.append("text fallback is missing")
    blocks = list(msg.get("blocks") or [])
    for a in msg.get("attachments") or []:
        blocks.extend(a.get("blocks") or [])
    if not blocks:
        errors.append("message has no blocks")
    errors.extend(validate_blocks(blocks))
    if len(msg.get("attachments") or []) > 20:
        errors.append("more than 20 attachments")
    return errors


def validate_view(view: dict[str, Any]) -> list[str]:
    errors = validate_blocks(view.get("blocks") or [], modal=True)
    _text_obj(errors, "title", view.get("title"), LIMITS["modal_title"], ("plain_text",))
    if view.get("submit"):
        _text_obj(errors, "submit", view["submit"], LIMITS["modal_title"], ("plain_text",))
    return errors


_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿⌀-⏿️‍\U0001f1e6-\U0001f1ff]")
_SHORTCODE = re.compile(r"(?<![\w/])(:[a-z_+][a-z0-9_+-]*:)(?![\w/])")


def message_texts(msg: Message) -> list[tuple[str, str]]:
    """(kind, text) for every human-readable string; kind 'quote' marks verbatim third-party quotes."""
    out: list[tuple[str, str]] = [("copy", msg.get("text", ""))]
    blocks = list(msg.get("blocks") or [])
    for a in msg.get("attachments") or []:
        out.append(("copy", a.get("fallback", "")))
        blocks.extend(a.get("blocks") or [])

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "text" in node and isinstance(node["text"], str):
                lines = node["text"].splitlines() or [""]
                quoted = [ln for ln in lines if ln.startswith(">")]
                own = [ln for ln in lines if not ln.startswith(">")]
                if quoted:
                    out.append(("quote", "\n".join(quoted)))
                out.append(("copy", "\n".join(own)))
            for k, v in node.items():
                if k in (
                    "action_id",
                    "block_id",
                    "value",
                    "url",
                    "private_metadata",
                    "callback_id",
                ):
                    continue
                if k == "text" and isinstance(v, str):
                    continue
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    return out


def lint_copy(msg: Message) -> list[str]:
    """No exclamation marks and no emoji in our own copy (C-AC-36). Verbatim quotes of other people's
    words are exempt, because they are evidence and are never rewritten."""
    problems: list[str] = []
    for kind, text in message_texts(msg):
        if kind == "quote":
            continue
        # strip links so URLs cannot trip the shortcode check
        plain = re.sub(r"<[^>|]*\|?([^>]*)>", r"\1", text)
        if "!" in plain:
            problems.append(f"exclamation mark in: {text[:60]!r}")
        if _EMOJI.search(text) or _SHORTCODE.search(plain):
            problems.append(f"emoji in: {text[:60]!r}")
    return problems
