from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from ..config import env, env_path


CONTENT_DIR = Path(__file__).resolve().parent / "content"


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    register: str
    title: str
    roles: dict[str, str]
    goal: str
    terms: list[str] = field(default_factory=list)
    source: str = "library"
    off_domain: bool = False

    @property
    def role_a(self) -> str:
        return self.roles.get("A", "担当者A")

    @property
    def role_b(self) -> str:
        return self.roles.get("B", "担当者B")


def _library() -> dict:
    return json.loads((CONTENT_DIR / "scenarios.json").read_text(encoding="utf-8"))


def load_categories() -> dict[str, str]:
    return _library().get("categories", {})


def load_scenarios() -> list[Scenario]:
    return [
        Scenario(
            id=str(item["id"]),
            category=str(item["category"]),
            register=str(item.get("register", "formal")),
            title=str(item["title"]),
            roles=dict(item.get("roles", {})),
            goal=str(item.get("goal", "")),
            terms=[str(term) for term in item.get("terms", [])],
        )
        for item in _library()["scenarios"]
    ]


def find_scenario(scenario_id: str) -> Scenario | None:
    for scenario in load_scenarios():
        if scenario.id == scenario_id:
            return scenario
    return None


def glossary_for(category: str) -> list[dict[str, str]]:
    """Common terms plus the category-specific block, used to ground the prompt."""
    payload = json.loads((CONTENT_DIR / "glossary.json").read_text(encoding="utf-8"))
    return [*payload.get("common", []), *payload.get(category, [])]


def work_dir() -> Path:
    return env_path("DAILY_WORK_DIR", "outputs/daily") or Path("outputs/daily")


def nas_dir() -> Path:
    return env_path("DAILY_NAS_DIR", "/mnt/nas/videos/TTS") or Path("/mnt/nas/videos/TTS")


def state_path() -> Path:
    return work_dir() / "state.json"


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return {"queue": [], "history": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"queue": [], "history": []}


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def next_scenario(state: dict) -> Scenario:
    """Take the head of the rotation queue, reshuffling the pool when it runs dry."""
    scenarios = load_scenarios()
    by_id = {scenario.id: scenario for scenario in scenarios}
    queue = [item for item in state.get("queue", []) if item in by_id]
    if not queue:
        queue = [scenario.id for scenario in scenarios]
        random.shuffle(queue)
    state["queue"] = queue
    return by_id[queue[0]]


def mark_used(state: dict, scenario: Scenario, date_str: str, stem: str) -> dict:
    """Drop the scenario from the queue and record it in history."""
    state["queue"] = [item for item in state.get("queue", []) if item != scenario.id]
    history = state.get("history", [])
    history.append({"date": date_str, "scenario_id": scenario.id, "stem": stem})
    state["history"] = history[-365:]
    return state


def adhoc_limit() -> int:
    raw = env("DAILY_ADHOC_LIMIT", "5") or "5"
    try:
        return max(0, int(raw))
    except ValueError:
        return 5


def history_path() -> Path:
    return work_dir() / "history.jsonl"


def append_history(entry: dict) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def adhoc_runs_today(date_str: str) -> int:
    path = history_path()
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("date") == date_str and entry.get("trigger") == "adhoc":
            count += 1
    return count
