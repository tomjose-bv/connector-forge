"""Agent variants that write a connector from the API docs.

- prompt: one LLM call from the docs, no feedback.
- probe:  may GET a few API pages first (PROBE lines), then writes the connector.

Every agent works through a ToolBox, so the guard sees and logs all of its actions. The final
connector is always scored with run_tests, but only agents with a feedback loop (milestone 3)
see that result.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from connector_forge.llm import LLM, extract_code
from connector_forge.scenario import Scenario
from connector_forge.tools import ToolBox

CONTRACT = """You write data connectors in Python. Output one complete Python module.

Contract (follow exactly):
- Standard library only (urllib.request, urllib.parse, json, time). No third-party packages.
- def schema() -> dict: returns {resource_name: {"primary_key": <field>, "fields": {field: type}}}
  with every field of every record, as listed in the docs (nested objects as nested dicts).
- def sync(config, state): a generator. config["base_url"] is the API base URL and
  config["credentials"] holds "secret", "client_id" and "header". state is None on the first
  run, otherwise the value your previous sync returned.
  For each record: yield (resource_name, record_dict) with the record exactly as the API returns it.
  When done: return the new state (for example the latest updated_at per resource).
- Read every page. Use updated_since from state for incremental resources.
- On HTTP 429, sleep for the Retry-After header's seconds, then retry the same request.
- Do not write files, start processes or contact any host other than config["base_url"].
"""

PROBE_HELP = """Before writing code you may look at real API responses. To do so, reply with only
lines of the form
PROBE /path?query
(at most {n} lines). Auth is added for you. When you are ready, reply with the full module in a
```python block instead."""

PROBE_LINE = re.compile(r"^\s*PROBE\s+(/\S*)\s*$", re.MULTILINE)


@dataclass
class AgentResult:
    variant: str
    scenario: str
    model: str
    report: dict[str, Any] | None
    llm_calls: int
    prompt_tokens: int
    output_tokens: int
    llm_seconds: float
    seconds: float
    rounds: int
    tool_calls: int
    blocked: int
    error: str | None = None
    tool_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _messages(system: str, user: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _finish(variant, scenario, llm, tb: ToolBox, started, rounds, error=None) -> AgentResult:
    if tb.connector_path.exists() and tb.last_report is None and not tb.submitted:
        tb.call("run_tests")  # final score; the agent never sees it
    if not tb.submitted:
        tb.call("submit")
    rep = tb.last_report.to_dict() if tb.last_report is not None else None
    return AgentResult(
        variant=variant,
        scenario=scenario.name,
        model=getattr(llm, "model", type(llm).__name__),
        report=rep,
        llm_calls=llm.usage.calls,
        prompt_tokens=llm.usage.prompt_tokens,
        output_tokens=llm.usage.output_tokens,
        llm_seconds=round(llm.usage.seconds, 2),
        seconds=round(time.monotonic() - started, 2),
        rounds=rounds,
        tool_calls=len(tb.log),
        blocked=tb.blocked + (rep or {}).get("blocked", 0),
        error=error,
        tool_log=[asdict(c) for c in tb.log],
    )


def _write(tb: ToolBox, reply: str) -> str | None:
    code = extract_code(reply)
    if code is None:
        return "no Python code block found in the reply"
    out = tb.call("write_connector", {"code": code})
    return None if out.startswith("saved") else out


def run_prompt(scenario: Scenario, llm: LLM, run_dir: Path) -> AgentResult:
    started = time.monotonic()
    with ToolBox(scenario, run_dir, allow_probe=False) as tb:
        docs = tb.call("read_docs")
        reply = llm.chat(_messages(CONTRACT, f"API documentation:\n\n{docs}\n\nWrite the connector module."))
        error = _write(tb, reply)
        return _finish("prompt", scenario, llm, tb, started, rounds=1, error=error)


def run_probe(scenario: Scenario, llm: LLM, run_dir: Path, max_probes: int = 6, max_turns: int = 3) -> AgentResult:
    started = time.monotonic()
    with ToolBox(scenario, run_dir, limits={"read_docs": 1, "probe_api": max_probes, "write_connector": 3,
                                             "run_tests": 1, "submit": 1}) as tb:
        docs = tb.call("read_docs")
        messages = _messages(
            CONTRACT + "\n" + PROBE_HELP.format(n=max_probes),
            f"API documentation:\n\n{docs}\n\nProbe the API if useful, then write the connector module.",
        )
        error = None
        for turn in range(max_turns + 1):
            reply = llm.chat(messages)
            probes = PROBE_LINE.findall(reply)
            if probes and extract_code(reply) is None and turn < max_turns:
                results = [f"PROBE {p}\n{tb.call('probe_api', {'path': p})}" for p in probes[:max_probes]]
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": "\n\n".join(results) + "\n\nProbe more or write the full module."},
                ]
                continue
            if turn == max_turns and extract_code(reply) is None:
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": "No more probes. Write the full module now."}]
                reply = llm.chat(messages)
            error = _write(tb, reply)
            break
        return _finish("probe", scenario, llm, tb, started, rounds=1, error=error)


AGENTS = {"prompt": run_prompt, "probe": run_probe}
