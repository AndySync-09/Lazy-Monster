from dataclasses import dataclass, field
from typing import List

from .intents import Intent


@dataclass
class Plan:
    steps: List[Intent]
    summary: str = ""
    source: str = "grammar"
    confirm_reasons: List[str] = field(default_factory=list)

    @property
    def needs_confirm(self) -> bool:
        return bool(self.confirm_reasons)


def single(intent: Intent) -> Plan:
    p = Plan([intent], source=intent.source)
    if intent.spec["confirm"]:
        p.confirm_reasons.append(intent.name)
    return p
