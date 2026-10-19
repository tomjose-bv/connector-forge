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


FIX_PROMPT = """Your connector was tested against the API: a full sync, then the API data changed and an
incremental sync ran with the state your first sync returned.

Test results:
{results}

Current module:
```python
{code}
```

Find the bugs and reply with the complete fixed module in one ```python block."""


def score(rep: dict[str, Any] | None) -> float:
    """Rank connector versions: accuracy first, then rate-limit compliance and efficiency."""
    if not rep:
        return -1.0
    s = rep["full_sync_accuracy"] + rep["incremental_accuracy"] + rep["schema_accuracy"]
    s -= 0.1 * min(rep["rate_violations"], 5) + 0.05 * bool(rep["refetched"]) + 0.2 * bool(rep["errors"])
    return s


def _probe_turn(tb: ToolBox, llm: LLM, messages: list[dict[str, str]], max_probes: int) -> str:
    reply = llm.chat(messages)
    probes = PROBE_LINE.findall(reply)
    if probes and extract_code(reply) is None:
        results = [f"PROBE {p}\n{tb.call('probe_api', {'path': p})}" for p in probes[:max_probes]]
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": "\n\n".join(results) + "\n\nNow write the full module."},
        ]
        reply = llm.chat(messages)
    return reply


def run_graph(scenario: Scenario, llm: LLM, run_dir: Path, rounds: int = 4, max_probes: int = 4) -> AgentResult:
    """Fixed plan: probe -> write -> (test -> fix) x rounds. The best tested version is final."""
    started = time.monotonic()
    limits = {"read_docs": 1, "probe_api": max_probes, "write_connector": rounds + 2, "run_tests": rounds + 1, "submit": 1}
    with ToolBox(scenario, run_dir, limits=limits) as tb:
        docs = tb.call("read_docs")
        system = CONTRACT + "\n" + PROBE_HELP.format(n=max_probes)
        reply = _probe_turn(tb, llm, _messages(system, f"API documentation:\n\n{docs}\n\nProbe the API if useful, "
                                                        "then write the connector module."), max_probes)
        best: tuple[float, str, Any] | None = None
        code, error, used = None, None, 0
        for used in range(1, rounds + 1):
            error = _write(tb, reply)
            if error and "no Python code" in error:
                results = "Your reply had no ```python code block."
            else:
                code = tb.connector_path.read_text(encoding="utf-8")
                results = tb.call("run_tests")
                s = score(tb.last_report.to_dict() if tb.last_report else None)
                if best is None or s > best[0]:
                    best = (s, code, tb.last_report)
                if "ALL CHECKS PASSED" in results:
                    break
            if used == rounds:
                break
            reply = llm.chat(_messages(CONTRACT, f"API documentation:\n\n{docs}\n\n"
                                                 + FIX_PROMPT.format(results=results, code=code or "(none)")))
        if best is not None:
            tb.connector_path.write_text(best[1], encoding="utf-8")
            tb.last_report = best[2]
            error = None
        return _finish("graph", scenario, llm, tb, started, rounds=used, error=error)


AGENTS["graph"] = run_graph
