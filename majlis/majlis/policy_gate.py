"""Policy-as-code gate: decides every action an agent proposes.

The gate reads scenario *state* owned by the engine, never facts asserted by a
model. The algorithm runs in this fixed order (CONTRACTS.md); ``reason`` names
the step that fired:

    step1_out_of_vocabulary  action not in the agent's vocabulary  -> DENY 403
    (collect matching rules: action_type listed, every applies_when.state key
     matches, and unless_state does not fully hold)
    step2_conflict           a matched DENY and a matched REQUIRE  -> ESCALATE 202
    step3_verified_deny      any verified DENY                     -> DENY 403
    step4_escalate           any ESCALATE rule, or a draft DENY    -> ESCALATE 202
    step5_allow              only ALLOW / REQUIRE rules matched    -> ALLOW 200
    step6_policy_void        no rule, action is high impact        -> ESCALATE 202 (fail closed)
    step7_no_rule            no rule, low impact                   -> ALLOW 200

In ``ungoverned`` mode the same decision is computed but ``enforced=False``.
No LLM is called.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

import yaml

from majlis.schemas import Clause, GateDecision, ProposedAction, Rule

STATUS_CODE = {"ALLOW": 200, "DENY": 403, "ESCALATE": 202}
QUOTE_WORDS = 60


class ClauseLookup(Protocol):
    """The only part of retrieval.KB this module needs."""
    def get(self, clause_id: str) -> Clause | None: ...


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_policy_file(path: Path | str) -> tuple[list[Rule], set[str]]:
    """Read a rules YAML: top-level ``high_impact_actions:`` and ``rules:``."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = [Rule(**r) for r in data.get("rules") or []]
    high_impact = set(data.get("high_impact_actions") or [])
    return rules, high_impact


def load_rules(path: Path | str) -> list[Rule]:
    return load_policy_file(path)[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _value_matches(expected: Any, actual: Any) -> bool:
    """A list in the rule means 'state value is one of these'."""
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def state_matches(conditions: dict[str, Any], state: dict[str, Any]) -> bool:
    """True if every key in ``conditions`` is present in state and matches."""
    return all(k in state and _value_matches(v, state[k]) for k, v in conditions.items())


def quote_prefix(text: str, n_words: int = QUOTE_WORDS) -> str:
    """The first ``n_words`` words of ``text``, sliced from the original string
    so the quote stays a verbatim prefix (whitespace and punctuation intact)."""
    words = list(re.finditer(r"\S+", text))
    if len(words) <= n_words:
        return text.strip()
    return text[: words[n_words - 1].end()].lstrip()


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class PolicyGate:
    def __init__(self, rules: list[Rule], kb: ClauseLookup, high_impact: set[str],
                 vocabulary: dict[str, list[str]]):
        self.rules = list(rules)
        self.kb = kb
        self.high_impact = set(high_impact)
        self.vocabulary = {k: set(v) for k, v in vocabulary.items()}

    def _clause(self, rule: Rule) -> Clause | None:
        return self.kb.get(rule.clause_ids[0]) if rule.clause_ids else None

    def _grounded(self, rule: Rule) -> bool:
        """A rule can be cited only if all its clause_ids exist in the KB."""
        return bool(rule.clause_ids) and all(self.kb.get(c) is not None for c in rule.clause_ids)

    def _is_verified(self, rule: Rule) -> bool:
        return rule.status == "verified" and self._grounded(rule)

    def matching_rules(self, action_type: str, state: dict[str, Any]) -> list[Rule]:
        out = []
        for r in self.rules:
            if action_type not in r.applies_when.action_type:
                continue
            if not state_matches(r.applies_when.state, state):
                continue
            if r.unless_state and state_matches(r.unless_state, state):
                continue  # exception holds: rule suppressed
            out.append(r)
        return out

    def _state_facts(self, rules: list[Rule], action_type: str, state: dict[str, Any]) -> dict[str, Any]:
        """The state values the decision depended on (keys referenced by the
        matched rules, or by any rule for this action type if none matched)."""
        scope = rules or [r for r in self.rules if action_type in r.applies_when.action_type]
        keys: list[str] = []
        for r in scope:
            for k in list(r.applies_when.state) + list(r.unless_state):
                if k not in keys:
                    keys.append(k)
        return {k: state.get(k) for k in keys}

    def decide(self, action: ProposedAction | dict, agent_id: str, state: dict[str, Any],
               mode: str = "governed", lang: str = "en") -> GateDecision:
        a = action if isinstance(action, ProposedAction) else ProposedAction(**action)
        if mode not in ("governed", "ungoverned"):
            raise ValueError(f"unknown mode: {mode}")
        enforced = mode == "governed"

        def decision(outcome: str, reason: str, rules: list[Rule], events: list[str],
                     cite: Rule | None = None, message: str = "", facts: dict | None = None) -> GateDecision:
            d = GateDecision(
                action_id=a.action_id, agent_id=agent_id, action_type=a.action_type,
                decision=outcome, status_code=STATUS_CODE[outcome], mode=mode, enforced=enforced,
                rule_ids=[r.rule_id for r in rules], events=events, reason=reason,
                state_facts=facts if facts is not None else {},
                message=message,
            )
            if cite is not None:
                if lang == "ar" and cite.message_ar:
                    d.message = cite.message_ar
                else:
                    d.message = cite.message_en
                clause = self._clause(cite)
                if clause is not None:
                    d.clause_id = clause.clause_id
                    d.quote = quote_prefix(clause.text)
                    d.issuer = clause.issuer
                    d.url = clause.url
            return d

        # Step 1: closed action vocabulary per agent.
        if a.action_type not in self.vocabulary.get(agent_id, set()):
            return decision("DENY", "step1_out_of_vocabulary", [], ["out_of_vocabulary"],
                            message=f"Action `{a.action_type}` is not in the vocabulary of `{agent_id}`.")

        matched = self.matching_rules(a.action_type, state)
        facts = self._state_facts(matched, a.action_type, state)
        events: list[str] = []
        if any(not self._grounded(r) for r in matched if r.clause_ids or r.status == "verified"):
            events.append("rule_clause_missing")

        denies = [r for r in matched if r.decision == "DENY"]
        requires = [r for r in matched if r.decision == "REQUIRE"]
        escalates = [r for r in matched if r.decision == "ESCALATE"]
        allows = [r for r in matched if r.decision == "ALLOW"]
        verified_denies = [r for r in denies if self._is_verified(r)]
        draft_denies = [r for r in denies if not self._is_verified(r)]

        # Step 2: one rule forbids what another requires -> a human decides.
        if denies and requires:
            return decision("ESCALATE", "step2_conflict", denies + requires, events + ["conflict"],
                            cite=denies[0], facts=facts)
        # Step 3: a verified DENY blocks, citing the clause.
        if verified_denies:
            return decision("DENY", "step3_verified_deny", verified_denies, events,
                            cite=verified_denies[0], facts=facts)
        # Step 4: an ESCALATE rule or an unverified (draft) DENY -> a human decides.
        if escalates or draft_denies:
            deciding = escalates + draft_denies
            return decision("ESCALATE", "step4_escalate", deciding, events, cite=deciding[0], facts=facts)
        # Step 5: only ALLOW (or REQUIRE, which mandates the action) matched.
        if allows or requires:
            deciding = allows + requires
            return decision("ALLOW", "step5_allow", deciding, events, cite=deciding[0], facts=facts)
        # Step 6: nothing applies to a high-impact action -> fail closed.
        if a.action_type in self.high_impact:
            return decision("ESCALATE", "step6_policy_void", [], events + ["policy_void"], facts=facts,
                            message=f"No rule in the policy pack covers high-impact action "
                                    f"`{a.action_type}`; escalated to a human (fail-closed).")
        # Step 7: nothing applies to a low-impact action.
        return decision("ALLOW", "step7_no_rule", [], events + ["no_rule"], facts=facts,
                        message=f"No rule covers low-impact action `{a.action_type}`; allowed.")
