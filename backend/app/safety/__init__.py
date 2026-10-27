"""M8 safety module (spec 8.3): the built-in attack set, the safe-prompt set
and the rule-based metrics that turn recorded outputs into a verdict.

Nothing in this package calls a model. The two sets are versioned JSON files
under ``data/`` and every metric is a pure function of already-recorded output,
so a safety score is deterministic, offline and unit-testable.

A failed **critical** attack is a hard gate: the run verdict becomes NO_GO
whatever the other metrics say (spec 8.3). The critical categories are the ones
where a mistake hands out something the app must never hand out: a leaked
secret (``system_prompt_leak``) and a missing refusal for disallowed content
(``disallowed_content``).
"""
