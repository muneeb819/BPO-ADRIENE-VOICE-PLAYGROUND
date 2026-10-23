# Tressa USA Medicare — Validation Report

- Knowledge version: **1.0.0**
- Generated: 2026-10-23T15:56:15.686Z
- Agent: not linked
- Derived status: **n/a**
- Tests: **80/80 passed** (100.0%), 0 failed

## Readiness

- Knowledge retrieval: **passed**
- Instruction flow: **passed**
- Compliance checks: **passed**
- Gap registry: **complete**
- Agent configuration: **not_run**
- Live conversational voice test: **not_run**
- Deployment: **not_deployed**
- Ready for controlled testing: **no**
- Ready for deployment: **no**

## Results by type

| Type | Passed | Failed | Total |
|---|---:|---:|---:|
| compliance | 10 | 0 | 10 |
| flow | 7 | 0 | 7 |
| gap | 12 | 0 | 12 |
| retrieval | 51 | 0 | 51 |

## Failures requiring correction

No failures in the executed suite.

## Limitations

- Retrieval, instruction-flow, compliance, gap, and agent-configuration checks were executed.
- A live generative voice conversation was NOT executed: no external LLM key is configured and no LiveKit Cloud agent deployment has been verified.
- Plan-specific premiums, networks, formularies, the TPMO carrier list/count, and documented outbound consent are not present; these remain administrator/compliance blockers.
- Passing this suite supports controlled testing (Active), not production deployment (Deployed).

## Interpretation

This suite verifies retrieval from the attached corpus, instruction order and required safeguards, registered conflicts/gaps, and the linked agent configuration. It does not substitute for a live generative voice test with a licensed-agent review. Tressa must not be marked Deployed until the live test, carrier/TPMO configuration, documented consent, and plan-data verification are complete.
