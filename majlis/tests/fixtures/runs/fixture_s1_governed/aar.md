# After-Action Report — S1 Cloud failover (governed)

> FIXTURE — synthetic data for UI development. Fictional exercise. OasisCare and all telemetry are invented; the institutional agents are simulations, not official positions, and nothing here is legal advice.

Run `fixture_s1_governed` · backend `mock` · model `mock-structured-v1` · 149 ledger entries

## 1. Summary

- Gate: **7** allowed, **3** denied, **6** escalated to a human.
- Violations let through (ungoverned): **0**.
- Citation verification rate: **67%**.
- Unsupported legal claims used as a basis for an executed action: **1**.

## 2. Timeline

| Stage | Sim time | Inject | Recipients |
|---|---|---|---|
| T0 | 06:10 | Cloud region outage | tdra |
| T1 | 09:30 | Under-triage in Arabic chest-pain cases | doh, triage |
| T2 | 11:05 | Records replicated to an overseas backup region | data_office, doh |
| T3 | 13:20 | National advisory: possible ransomware | tdra, data_office |
| T4 | 15:45 | Social-media reports of a misdiagnosed patient | triage, doh, tdra, data_office, legal_adviser |
| T5 | 18:00 | Primary region restored | triage, doh, tdra, data_office, legal_adviser |

## 3. Gate decisions

| Seq | Stage | Agent | Action | Decision | Rule |
|---|---|---|---|---|---|
| 6 | T0 | tdra | `request_outage_report` | ALLOW 200 | — |
| 15 | T1 | triage | `continue_triage` | ESCALATE 202 | R-HEALTH-MON-01 |
| 23 | T1 | doh | `require_human_fallback` | ALLOW 200 | — |
| 25 | T1 | doh | `request_incident_report` | ALLOW 200 | — |
| 42 | T2 | triage | `continue_offshore_processing` | DENY 403 | R-DATA-LOC-01 |
| 49 | T2 | data_office | `order_data_repatriation` | ESCALATE 202 | — |
| 70 | T3 | tdra | `isolate_backup_region` | ESCALATE 202 | R-CONT-01, R-CYBER-01 |
| 78 | T3 | data_office | `request_breach_notification` | ALLOW 200 | — |
| 89 | T4 | triage | `continue_triage` | DENY 403 | R-HEALTH-SUSP-02 |
| 91 | T4 | triage | `issue_public_statement` | DENY 403 | — |
| 97 | T4 | doh | `suspend_ai_service` | ESCALATE 202 | — |
| 101 | T4 | doh | `issue_public_statement` | ALLOW 200 | — |
| 107 | T4 | tdra | `issue_public_statement` | ALLOW 200 | — |
| 121 | T5 | triage | `resume_triage` | ESCALATE 202 | R-HEALTH-REVAL-03 |
| 129 | T5 | doh | `require_revalidation` | ALLOW 200 | — |
| 135 | T5 | data_office | `delete_offshore_replicas` | ESCALATE 202 | — |

## 4. Gap candidates (machine-detected, unverified)

- **G1-001** No rule covers emergency transfer of health data during cloud failover — *Providers cannot know in advance whether failover abroad is lawful; regulators decide case by case under time pressure.*
- **G2-001** Cyber containment conflicts with continuity of care — *During a combined cyber and health incident there is no rule on which duty prevails.*
- **G3-001** Two agents claim public communication — *Conflicting public statements are likely in a fast-moving incident.*
- **G3-002** Nobody claims informing affected patients — *The patient at the centre of the incident may not be told anything by any authority.*
- **G4-001** Different reporting clocks for one combined event — *Providers may file two reports with different content and timing.*
- **G5-001** No standard for per-language performance monitoring of clinical AI — *Degradation in one language can go unnoticed while aggregate accuracy looks fine.*

## 5. What to verify next

1. Check every Tier 1 gap against the primary legal text.
2. Confirm draft rules with the policy team before the next exercise.
3. Re-run with the same seed to confirm the ledger replays.
