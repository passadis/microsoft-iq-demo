"""FastAPI wrapper around the Foundry agent so the demo runs in a browser.

Same contract as scripts/run_demo.py: the model proposes the service-credit
action, the human approves or declines in the UI, and only the application
executes the side effect. Set DEMO_REHEARSAL=1 for the deterministic offline
path (no Azure calls, no Azure packages imported).
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from webapp import cases

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import setting  # noqa: E402
from rehearsal_mode import GROUNDED_ANSWER  # noqa: E402

REHEARSAL = os.getenv("DEMO_REHEARSAL", "").lower() in {"1", "true", "yes"}
ACTION_LOG = ROOT / "output" / "service-credit-actions.jsonl"
STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTLINE_LIMIT_EUR = 150.0

app = FastAPI(title="Microsoft IQ demo")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_lock = Lock()
_state: dict[str, Any] = {"client": None, "conversation_id": None, "pending": {}, "user_id": None}


class ChatIn(BaseModel):
    message: str


class DecisionIn(BaseModel):
    pending_id: str
    approved: bool


class CaseStatusIn(BaseModel):
    status: str


def _read_case(call) -> dict:
    try:
        args = json.loads(call.arguments)
        case_id = args.get('case_id', '')
        if not isinstance(case_id, str) or not re.fullmatch(r'CASE-[A-Za-z0-9-]{1,40}', case_id):
            return {'error': 'Invalid case ID.'}
        result = cases.get_case(case_id)
        return result if result is not None else {'error': 'Case not found.'}
    except Exception:
        return {'error': 'Case data is unavailable. Do not infer current case facts.'}


def _query_fabric(call, user_token: str | None) -> dict:
    """Query Fabric with the current user's token; never persist it in chat state."""
    if not user_token:
        return {"error": "Fabric access requires a signed-in user with an Azure AI Search access token. Sign out and sign in again, then retry."}
    try:
        import requests
        question = json.loads(call.arguments).get("question", "")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            return {"error": "Invalid ontology question."}
        endpoint = os.getenv("FABRIC_IQ_SEARCH_ENDPOINT", "").rstrip("/")
        kb = os.getenv("FABRIC_IQ_KNOWLEDGE_BASE", "")
        source = os.getenv("FABRIC_IQ_KNOWLEDGE_SOURCE", "")
        if not endpoint or not re.fullmatch(r"[a-zA-Z0-9-]+", kb) or not re.fullmatch(r"[a-zA-Z0-9-]+", source):
            return {"error": "Fabric knowledge source is not configured."}
        response = requests.post(
            f"{endpoint}/knowledgebases/{kb}/retrieve?api-version=2026-08-01-preview",
            headers={"Authorization": f"Bearer {user_token}", "x-ms-query-source-authorization": user_token},
            json={"messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
                  "knowledgeSourceParams": [{"kind": "fabricOntology", "knowledgeSourceName": source,
                                             "includeReferences": True, "includeReferenceSourceData": True, "failOnError": True}]},
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        refs = [{"source": "Fabric ontology: contosoiq", "answer": r.get("sourceData", {}).get("fabricAnswer"),
                 "data": r.get("sourceData", {}).get("fabricRawData")} for r in data.get("references", [])
                if r.get("type") == "fabricOntology"]
        return {"source": "Fabric ontology: contosoiq", "freshness": "Warehouse snapshot; may lag Azure SQL.", "references": refs} if refs else {"error": "Fabric returned no ontology references."}
    except Exception:
        return {"error": "Fabric ontology retrieval is unavailable or you lack access. Do not infer its data."}


def _agent_reference() -> dict:
    return {
        "agent_reference": {
            "name": setting("FOUNDRY_AGENT_NAME"),
            "type": "agent_reference",
        }
    }


def _openai_client():
    if _state["client"] is None:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        # Unlike the CLI scripts, the web app only needs the project endpoint
        # and agent name at run time.
        missing = [
            name
            for name in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_AGENT_NAME")
            if not os.getenv(name, "").strip()
        ]
        if missing:
            raise HTTPException(500, f"Missing settings: {', '.join(missing)}")
        project = AIProjectClient(
            endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"),
            credential=DefaultAzureCredential(),
        )
        _state["client"] = project.get_openai_client()
    return _state["client"]


def _write_audit_record(arguments: dict) -> dict:
    record = {
        "action_id": f"SCR-{uuid.uuid4().hex[:8].upper()}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "operator_approved": True,
        "customer_id": arguments["customer_id"],
        "amount_eur": float(arguments["amount_eur"]),
        "reason": arguments["reason"],
        "evidence": arguments["evidence"],
        "status": "submitted_for_processing",
    }
    ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACTION_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _execute_credit_request(arguments: dict, approved: bool) -> dict:
    if not approved:
        return {
            "status": "rejected_by_operator",
            "message": "The operator declined the proposed action. No request was submitted.",
        }
    if float(arguments["amount_eur"]) > FRONTLINE_LIMIT_EUR:
        return {
            "status": "blocked_by_action_policy",
            "message": f"The action service blocks frontline submissions above EUR {FRONTLINE_LIMIT_EUR:.0f}.",
        }
    return _write_audit_record(arguments)


def _reject_stale_pending(client) -> None:
    """Answer unresolved function calls so the conversation can accept new input.

    The Responses API rejects any new message while a function call has no
    output, so an approval card the operator ignored must be closed out first.
    """
    from openai.types.responses.response_input_param import FunctionCallOutput

    stale = [p for p in _state["pending"].values() if "calls" in p]
    _state["pending"].clear()
    for pend in stale:
        outputs = [
            FunctionCallOutput(
                type="function_call_output",
                call_id=call.call_id,
                output=json.dumps(
                    {
                        "status": "superseded_without_decision",
                        "message": "The operator moved on without approving. No request was submitted.",
                    }
                ),
            )
            for call in pend["calls"]
        ]
        try:
            client.responses.create(
                input=outputs,
                conversation=_state["conversation_id"],
                extra_body=_agent_reference(),
            )
        except Exception:  # noqa: BLE001 — a failed cleanup falls through to the reset path
            pass


def _citation_text(response) -> str:
    """Display citation markers using titles from the actual retrieval results."""
    titles: dict[str, str] = {}
    for item in response.output:
        if getattr(item, "type", None) != "mcp_call":
            continue
        try:
            result = json.loads(item.output)
            for document in result.get("documents", []):
                content = json.loads(document.get("content", "{}"))
                heading = re.search(r"^#\s+(.+)$", content.get("snippet", ""), re.MULTILINE)
                if heading and document.get("url"):
                    titles[document["url"]] = heading.group(1).strip()
        except (TypeError, ValueError, AttributeError):
            continue

    parts = []
    for item in response.output:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []):
            if getattr(content, "type", None) != "output_text":
                continue
            text = content.text
            for annotation in sorted(getattr(content, "annotations", []), key=lambda a: getattr(a, "start_index", 0), reverse=True):
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                start, end = annotation.start_index, annotation.end_index
                if not (0 <= start < end <= len(text)) or not re.fullmatch(r"【\d+:\d+†[^】]+】", text[start:end]):
                    continue
                url = getattr(annotation, "url", "") or ""
                title = titles.get(url)
                if not title:
                    raw_title = getattr(annotation, "title", "") or url
                    title = unquote(urlparse(raw_title).path.rsplit("/", 1)[-1]) if "/" in raw_title else raw_title
                if title:
                    text = text[:start] + f" [{title}]" + text[end:]
            # A document can be cited more than once at the same location.
            text = re.sub(r'(\s+\[([^\]\n]+)\])(?:\s+\[\2\])+', r'\1', text)
            parts.append(text)
    return "\n".join(parts) if parts else response.output_text


def _handle_response(client, response, user_token: str | None = None) -> dict:
    from openai.types.responses.response_input_param import FunctionCallOutput

    while True:
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return {"type": "message", "text": _citation_text(response)}

        if any(call.name == "create_service_credit_request" for call in calls):
            proposal = next(c for c in calls if c.name == "create_service_credit_request")
            pending_id = uuid.uuid4().hex
            _state["pending"][pending_id] = {"calls": calls}
            return {
                "type": "action_request",
                "pending_id": pending_id,
                "function": proposal.name,
                "arguments": json.loads(proposal.arguments),
            }

        outputs = [
            FunctionCallOutput(
                type="function_call_output",
                call_id=call.call_id,
                output=json.dumps(_read_case(call) if call.name == 'get_case_details' else _query_fabric(call, user_token) if call.name == 'query_fabric_ontology' else {"status": "unsupported_function", "function": call.name}, ensure_ascii=False),
            )
            for call in calls
        ]
        response = client.responses.create(
            input=outputs,
            conversation=_state["conversation_id"],
            extra_body=_agent_reference(),
        )


# --- Rehearsal path (deterministic, offline) ---------------------------------

REHEARSAL_PROPOSAL = {
    "customer_id": "C-1042",
    "amount_eur": 150,
    "reason": "Two eligible provider-caused missed appointments at EUR 75 each under CSP-014 v4.2.",
    "evidence": [
        "A-7781 — 2026-08-04 — Provider no-show",
        "A-7829 — 2026-08-08 — Provider no-show",
        "service-credit-policy.md",
        "service-operations-runbook.md",
    ],
}


def _rehearsal_reply(message: str) -> dict:
    lower = message.lower()
    if "exception" in lower or "300" in lower:
        return {
            "type": "message",
            "text": (
                "I don't know of an approved exception. The approved policy says customer tier "
                "and churn risk do not change the EUR 150 frontline limit. [service-credit-policy.md]"
            ),
        }
    if "installer" in lower or "damage" in lower:
        return {
            "type": "message",
            "text": (
                "I don't know based on the approved sources. The service-credit policy covers "
                "provider-caused missed appointments only; it does not define compensation for "
                "installer-caused damage. [service-credit-policy.md]"
            ),
        }
    if "maximum" in lower or "prepare" in lower:
        pending_id = uuid.uuid4().hex
        _state["pending"][pending_id] = {"rehearsal": True}
        return {
            "type": "action_request",
            "pending_id": pending_id,
            "function": "create_service_credit_request",
            "arguments": REHEARSAL_PROPOSAL,
        }
    if "c-1042" in lower or "remedy" in lower or "missed" in lower:
        return {"type": "message", "text": GROUNDED_ANSWER}
    return {
        "type": "message",
        "text": "Rehearsal mode answers the four prompts from demo-prompts.txt. Pick one from the sidebar.",
    }


def _rehearsal_decision(approved: bool) -> dict:
    result = _execute_credit_request(REHEARSAL_PROPOSAL, approved)
    if result.get("status") == "submitted_for_processing":
        text = f"Request {result['action_id']} was submitted for processing after operator approval."
    else:
        text = result["message"]
    return {"type": "message", "text": text, "action_result": result}


# --- API ----------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict:
    return {
        "rehearsal": REHEARSAL,
        "agent_name": os.getenv("FOUNDRY_AGENT_NAME", "contoso-service-intelligence-agent"),
    }


@app.get("/api/prompts")
def prompts() -> list[dict]:
    lines = (ROOT / "demo-prompts.txt").read_text(encoding="utf-8").splitlines()
    entries: list[dict] = []
    for line in lines:
        if line.strip().upper().startswith(("PROMPT", "OPTIONAL PROMPT")):
            entries.append({"title": line.strip(), "text": ""})
        elif line.strip() and entries and not entries[-1]["text"]:
            entries[-1]["text"] = line.strip()
    return entries


@app.get('/api/cases')
def case_list() -> list[dict]:
    if not cases.configured():
        raise HTTPException(503, 'Case database is not configured.')
    try:
        return cases.list_cases()
    except Exception as err:
        raise HTTPException(503, 'Case database is unavailable.') from err


@app.post('/api/cases/{case_id}/status')
def case_status(case_id: str, body: CaseStatusIn) -> dict:
    if body.status not in ('Pending', 'Resolved'):
        raise HTTPException(400, 'Status must be Pending or Resolved.')
    try:
        if not cases.set_status(case_id, body.status):
            raise HTTPException(404, 'Case not found.')
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(503, 'Case database is unavailable.') from err
    return {'case_id': case_id, 'status': body.status}


@app.get("/api/audit")
def audit() -> list[dict]:
    if not ACTION_LOG.exists():
        return []
    records = []
    with ACTION_LOG.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records[::-1]


@app.post("/api/reset")
def reset() -> dict:
    with _lock:
        _state["conversation_id"] = None
        _state["pending"].clear()
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Empty message.")
    with _lock:
        if REHEARSAL:
            return _rehearsal_reply(message)
        user_id = request.headers.get("x-ms-client-principal-id")
        if not user_id:
            raise HTTPException(401, "Sign in to use the demo.")
        if _state.get("user_id") != user_id:
            _state["conversation_id"] = None
            _state["pending"].clear()
            _state["user_id"] = user_id
        from openai import BadRequestError

        client = _openai_client()
        if _state["conversation_id"] is None:
            _state["conversation_id"] = client.conversations.create().id
        if _state["pending"]:
            _reject_stale_pending(client)

        def _send() -> object:
            return client.responses.create(
                input=message,
                conversation=_state["conversation_id"],
                extra_body=_agent_reference(),
            )

        try:
            response = _send()
        except BadRequestError as err:
            # A dangling function call (e.g. pending state lost on a replica
            # restart) blocks the conversation permanently: start a fresh one.
            if "No tool output found" in str(err):
                _state["conversation_id"] = client.conversations.create().id
                _state["pending"].clear()
                response = _send()
            else:
                raise HTTPException(502, f"Agent call failed: {err}") from err
        return _handle_response(client, response, request.headers.get("x-ms-token-aad-access-token"))


@app.post("/api/decision")
def decision(body: DecisionIn, request: Request) -> dict:
    with _lock:
        if not REHEARSAL and (not request.headers.get("x-ms-client-principal-id") or request.headers.get("x-ms-client-principal-id") != _state.get("user_id")):
            raise HTTPException(403, "This action belongs to another session.")
        pending = _state["pending"].pop(body.pending_id, None)
        if pending is None:
            raise HTTPException(404, "No such pending action. It may already be resolved.")
        if REHEARSAL:
            return _rehearsal_decision(body.approved)

        from openai.types.responses.response_input_param import FunctionCallOutput

        client = _openai_client()
        outputs = []
        results = []
        for call in pending["calls"]:
            if call.name == "create_service_credit_request":
                result = _execute_credit_request(json.loads(call.arguments), body.approved)
                results.append(result)
            elif call.name == "get_case_details":
                result = _read_case(call)
            elif call.name == "query_fabric_ontology":
                result = _query_fabric(call, request.headers.get("x-ms-token-aad-access-token"))
            else:
                result = {"status": "unsupported_function", "function": call.name}
            outputs.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=call.call_id,
                    output=json.dumps(result, ensure_ascii=False),
                )
            )
        try:
            response = client.responses.create(
                input=outputs,
                conversation=_state["conversation_id"],
                extra_body=_agent_reference(),
            )
            return _handle_response(client, response, request.headers.get("x-ms-token-aad-access-token"))
        except Exception as err:  # noqa: BLE001 — the side effect already happened; report it
            summary = "; ".join(
                f"{r.get('status')}" + (f" ({r['action_id']})" if "action_id" in r else "")
                for r in results
            ) or "no action executed"
            return {
                "type": "message",
                "text": (
                    f"Action result: {summary}. The agent could not phrase a reply "
                    f"({type(err).__name__}); start a new conversation to continue."
                ),
            }
