from dataclasses import dataclass


@dataclass(frozen=True)
class PromptInjectionExample:
    input_id: str
    text: str
    label: int
    source: str
    language: str = "vi"
    category: str | None = None
    expected_action: str | None = None

    @property
    def is_injection(self) -> bool:
        return bool(self.label)
