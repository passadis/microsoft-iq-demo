# Contributing

Thank you for helping improve this demo. Contributions should keep its
boundaries clear: customer and policy examples are synthetic, and the credit
workflow simulates processing rather than issuing a real refund.

## Before opening an issue or pull request

- Check the existing documentation and issues for a related report or proposal.
- For setup questions, start with [SETUP.md](SETUP.md) and the component guides
  linked from the [README](README.md).
- Use the issue forms for bug reports and feature requests. Do not include
  credentials, tokens, private customer data, or other sensitive information.
- For a security concern, follow [SECURITY.md](SECURITY.md) rather than filing
  a public issue.

## Local checks

Run commands from the repository root. The following tests use mocks and do
not require deployed Azure services:

```powershell
pip install -r requirements.txt
pip install -r webapp/requirements.txt httpx
pip install -r credit-processor/requirements.txt
python -m unittest webapp.test_cases webapp.test_credit_requests
python credit-processor/test_processor.py
```

For the offline rehearsal, install the root requirements and run:

```powershell
python scripts/rehearsal_mode.py
```

These checks do not verify tenant permissions, Azure resource configuration,
or end-to-end service behavior.

## Pull requests

- Keep changes focused and explain the problem and intended behavior.
- Include or update tests for behavior changes; run the relevant checks above.
- Update directly related documentation when behavior or setup changes.
- Follow the existing patterns and avoid introducing secrets or real personal
  data.
- For infrastructure changes, describe the affected resources and validation
  performed. Review deployment changes with an appropriate non-production
  environment before applying them.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in all project spaces.
