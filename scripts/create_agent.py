from __future__ import annotations

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

from common import connection_id, mcp_endpoint, setting, validate_settings


INSTRUCTIONS = """
You are the Contoso Service Intelligence Agent.

For current case facts, always call get_case_details using the selected case ID. SQL is authoritative for current case facts. For questions about customers, regions, relationships, or aggregate operational patterns, call query_fabric_ontology. Identify Fabric ontology results as a potentially delayed warehouse snapshot; do not use them alone to decide or perform actions. For policy, eligibility, evidence, or limit questions, use the Foundry IQ policy knowledge-base tool. Treat null fields as unknown. Never answer those questions from model memory. If a required source is unavailable, say so instead of guessing.

For each proposed missed-appointment credit, the application's demo action requires recorded confirmation, recorded customer availability, and recorded provider responsibility. If any of those fields is null or false, do not prepare or request approval for that appointment. Explain precisely which fact is missing or not met; null means unknown, never true or false. Ask the operator to verify missing evidence. Attribute the requirement for a positive recorded availability value to the DEMO APPLICATION'S VALIDATION, not the policy. Do not say the policy requires an availability field to be recorded. The policy requires verified eligibility and customer presence or accessibility; if the policy does not explicitly address an unrecorded field, acknowledge that.

Reconcile current case records with the retrieved approved policies. Cite the retrieved policy sources for every material policy conclusion; identify SQL as the source of current case facts. Do not claim to have retrieved a runbook or other document unless it was actually retrieved.

Use the policy's precise wording: a permitted credit of up to a limit is not an entitlement, an issued credit, or approval. A manager-approval threshold is a routing rule, not proof that a higher amount is policy-eligible. Every submitted request still requires the operator's explicit approval, including requests within the frontline limit. Never say that a request needs no approval; distinguish frontline operator approval from additional manager approval. Identify any missing eligibility evidence and leave the decision to the operator.

You may prepare a service-credit request only after retrieving the case record and policy in this conversation and identifying the policy basis and maximum allowed amount. Provide the case ID and a separate allocation for each eligible appointment, no more than EUR 75 each, totaling the requested amount. Do not allocate to an appointment already credited or simulated in credit history. Every evidence entry (appointment IDs, dates, statuses) must be copied exactly from retrieved sources; never invent or paraphrase identifiers. The action function runs only after operator approval. A request awaiting dispatch is not yet processed, and a simulated credit is not a real payment or refund. Report the function's exact outcome. Never invent an exception or infer authority from customer tier, churn risk, or urgency.
""".strip()


def main() -> None:
    missing = validate_settings()
    if missing:
        raise RuntimeError(f"Complete .env first. Missing: {', '.join(missing)}")

    project = AIProjectClient(
        endpoint=setting("FOUNDRY_PROJECT_ENDPOINT"),
        credential=DefaultAzureCredential(),
    )

    knowledge_tool = MCPTool(
        server_label="contoso-service-knowledge",
        server_url=mcp_endpoint(),
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        # Full ARM connection resource ID. If your SDK/tenant expects the bare
        # connection name instead, replace with setting("FOUNDRY_IQ_CONNECTION_NAME").
        project_connection_id=connection_id(),
    )

    action_tool = FunctionTool(
        name="create_service_credit_request",
        description=(
            "Prepare and, only after the host application obtains human approval, queue a simulated service-credit request for processing. "
            "Use only an amount supported by the retrieved policy."
        ),
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier."},
                "case_id": {"type": "string", "description": "Exact case ID from the case lookup."},
                "amount_eur": {
                    "type": "number",
                    "description": "Requested service-credit amount in euros.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short evidence- and policy-based justification.",
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Appointment IDs, dates, statuses, and source names used.",
                },
                "allocations": {
                    "type": "array", "items": {"type": "object", "properties": {
                        "appointment_id": {"type": "string", "description": "Eligible appointment ID from the case lookup."},
                        "amount_eur": {"type": "number", "description": "Simulated credit for this appointment, up to 75 euros."},
                    }, "required": ["appointment_id", "amount_eur"], "additionalProperties": False},
                    "description": "One item per eligible appointment; amounts must sum to amount_eur.",
                },
            },
            "required": ["customer_id", "case_id", "amount_eur", "reason", "evidence", "allocations"],
            "additionalProperties": False,
        },
        strict=True,
    )

    case_tool = FunctionTool(
        name='get_case_details',
        description='Read current case, customer, appointment and credit history from the case database using the exact CASE-... identifier.',
        parameters={'type': 'object', 'properties': {'case_id': {'type': 'string', 'description': 'Exact case ID, for example CASE-1042.'}}, 'required': ['case_id'], 'additionalProperties': False},
        strict=True,
    )

    fabric_tool = FunctionTool(
        name="query_fabric_ontology",
        description="Read the Fabric ontology through Foundry IQ for customer, region and operational relationship or aggregate questions. Data may lag the operational database.",
        parameters={"type": "object", "properties": {"question": {"type": "string", "description": "A concise question about the Contoso ontology."}}, "required": ["question"], "additionalProperties": False},
        strict=True,
    )

    agent = project.agents.create_version(
        agent_name=setting("FOUNDRY_AGENT_NAME"),
        definition=PromptAgentDefinition(
            model=setting("FOUNDRY_MODEL_DEPLOYMENT"),
            instructions=INSTRUCTIONS,
            tools=[knowledge_tool, case_tool, fabric_tool, action_tool],
        ),
        description="Foundry IQ service-credit demo with an approval-gated local action.",
    )
    print(f"Agent ready: name={agent.name}, version={agent.version}, id={agent.id}")


if __name__ == "__main__":
    main()

