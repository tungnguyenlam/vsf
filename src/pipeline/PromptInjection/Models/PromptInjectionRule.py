from dataclasses import dataclass


@dataclass(frozen=True)
class PromptInjectionRule:
    name: str
    category: str
    pattern: str
    weight: float
    description: str
    ignore_case: bool = True
