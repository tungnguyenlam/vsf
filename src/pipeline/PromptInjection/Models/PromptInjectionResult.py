from dataclasses import asdict, dataclass, field


@dataclass
class PromptInjectionResult:
    is_injection: bool
    score: float
    action: str
    matched_rules: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
