from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses.response_input_param import FunctionCallOutput

from common import ROOT, setting, validate_settings


ACTION_LOG = ROOT / "output" / "service-credit-actions.jsonl"


def execute_credit_request(arguments: dict) -> dict:
    print("\n--- GOVERNED ACTION REQUEST ---")
    print(json.dumps(arguments, indent=2, ensure_ascii=False))
    print("The model has proposed arguments; no side effect has occurred.")
    approved = input("Approve submission? [y/N]: ").strip().lower() == "y"

    if not approved:
        return {
            "status": "rejected_by_operator",
            "message": "The operator declined the proposed action. No request was submitted.",
        }

    amount = float(arguments["amount_eur"])
    if amount > 150:
        return {
            "status": "blocked_by_action_policy",
            "message": "The action service blocks frontline submissions above EUR 150.",
        }

    record = {
        "action_id": f"SCR-{uuid.uuid4().hex[:8].upper()}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "operator_approved": True,
        "customer_id": arguments["customer_id"],
        "amount_eur": amount,
        "reason": arguments["reason"],
        "evidence": arguments["evidence"],
        "status": "submitted_for_processing",
    }
    ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACTION_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def continue_function_calls(openai_client, conversation_id: str, response):
    while True:
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return response

        outputs = []
        for call in calls:
            if call.name != "create_service_credit_request":
                result = {"status": "unsupported_function", "function": call.name}
            else:
                result = execute_credit_request(json.loads(call.arguments))
            outputs.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=call.call_id,
                    output=json.dumps(result, ensure_ascii=False),
                )
            )

        response = openai_client.responses.create(
            input=outputs,
            conversation=conversation_id,
            extra_body={
                "agent_reference": {
                    "name": setting("FOUNDRY_AGENT_NAME"),
                    "type": "agent_reference",
                }
            },
        )


def main() -> None:
    missing = validate_settings()
    if missing:
        raise RuntimeError(f"Complete .env first. Missing: {', '.join(missing)}")

    project = AIProjectClient(
        endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"),
        credential=DefaultAzureCredential(),
    )
    openai_client = project.get_openai_client()
    conversation = openai_client.conversations.create()

    print("Contoso Service Intelligence Agent")
    print("Type 'exit' to end. Use the prompts in demo-prompts.txt.\n")

    try:
        while True:
            try:
                prompt = input("You> ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                break
            if prompt.lower() in {"exit", "quit"}:
                break
            if not prompt:
                continue

            response = openai_client.responses.create(
                input=prompt,
                conversation=conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": setting("FOUNDRY_AGENT_NAME"),
                        "type": "agent_reference",
                    }
                },
            )
            response = continue_function_calls(openai_client, conversation.id, response)
            print(f"\nAgent> {response.output_text}\n")
    finally:
        try:
            openai_client.conversations.delete(conversation_id=conversation.id)
        except Exception:
            pass


if __name__ == "__main__":
    main()

