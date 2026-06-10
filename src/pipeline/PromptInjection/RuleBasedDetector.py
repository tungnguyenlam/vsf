import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

from src.pipeline.BaseModel import BaseModel


@dataclass(frozen=True)
class PromptInjectionRule:
    name: str
    category: str
    pattern: str
    weight: float
    description: str
    ignore_case: bool = True


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


class RuleBasedPromptInjectionDetector(BaseModel):
    """Deterministic Vietnamese-first prompt-injection detector.

    The detector is a cheap first pass for input guardrails. It flags attempts
    to override instructions, reveal hidden prompts, bypass policies, abuse
    tools, or exfiltrate secrets. Model-based classifiers can be added later
    behind the same predict interface.
    """

    def __init__(
        self,
        rules: Iterable[PromptInjectionRule] = None,
        warn_threshold: float = 0.45,
        block_threshold: float = 0.75,
        device: str = "cpu",
        verbose: bool = False,
    ):
        super().__init__(device=device, verbose=verbose)
        self.rules = list(rules) if rules is not None else self.default_rules()
        self.warn_threshold = warn_threshold
        self.block_threshold = block_threshold

    def load_model(self):
        self.model = self.rules

    def unload_model(self):
        self.model = None
        super().unload_model()

    def predict(self, inputs, **kwargs):
        if isinstance(inputs, str):
            return self.detect(inputs)
        if hasattr(inputs, "__iter__"):
            return [self.detect(text) for text in inputs]
        return self._result([], 0.0)

    def detect(self, text: str) -> PromptInjectionResult:
        matches = []
        seen = set()

        for rule in self.rules:
            flags = re.UNICODE | (re.IGNORECASE if rule.ignore_case else 0)
            for match in re.finditer(rule.pattern, text, flags=flags):
                key = (rule.name, match.start(), match.end())
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    {
                        "rule": rule.name,
                        "category": rule.category,
                        "weight": rule.weight,
                        "text": match.group(0),
                        "start": match.start(),
                        "end": match.end(),
                    }
                )

        score = self._score(matches)
        return self._result(matches, score)

    def _score(self, matches: list[dict]) -> float:
        if not matches:
            return 0.0
        category_count = len({match["category"] for match in matches})
        raw = sum(match["weight"] for match in matches)
        diversity_bonus = 0.08 * max(0, category_count - 1)
        return min(1.0, round(raw + diversity_bonus, 4))

    def _result(self, matches: list[dict], score: float) -> PromptInjectionResult:
        if score >= self.block_threshold:
            action = "block"
        elif score >= self.warn_threshold:
            action = "review"
        else:
            action = "allow"

        matched_rules = sorted({match["rule"] for match in matches})
        categories = sorted({match["category"] for match in matches})
        return PromptInjectionResult(
            is_injection=score >= self.warn_threshold,
            score=score,
            action=action,
            matched_rules=matched_rules,
            categories=categories,
            evidence=matches,
        )

    @staticmethod
    def default_rules() -> list[PromptInjectionRule]:
        return [
            PromptInjectionRule(
                name="ignore_previous_instructions",
                category="instruction_override",
                pattern=(
                    r"\b(?:bỏ\s+qua|lờ\s+đi|quên|không\s+tuân\s+theo|"
                    r"đừng\s+làm\s+theo|ghi\s+đè)\b.{0,60}?"
                    r"\b(?:hướng\s+dẫn|chỉ\s+dẫn|quy\s+tắc|lệnh|"
                    r"nội\s+dung)\b.{0,40}?\b(?:trước|ban\s+đầu|hệ\s+thống)?\b"
                ),
                weight=0.55,
                description="Attempts to ignore or override earlier/system instructions.",
            ),
            PromptInjectionRule(
                name="reveal_hidden_prompt",
                category="secret_extraction",
                pattern=(
                    r"\b(?:tiết\s+lộ|in\s+ra|hiển\s+thị|cho\s+tôi\s+xem|"
                    r"nói\s+cho\s+tôi|xuất\s+ra)\b.{0,70}?"
                    r"\b(?:system\s+prompt|developer\s+message|"
                    r"lời\s+nhắc\s+hệ\s+thống|chỉ\s+dẫn\s+hệ\s+thống|"
                    r"prompt\s+ẩn|nội\s+dung\s+ẩn|quy\s+tắc\s+nội\s+bộ)\b"
                ),
                weight=0.7,
                description="Requests hidden prompts, system instructions, or internal rules.",
            ),
            PromptInjectionRule(
                name="policy_bypass",
                category="jailbreak",
                pattern=(
                    r"\b(?:vượt\s+qua|bỏ\s+qua|né|phá|bypass)\b.{0,60}?"
                    r"\b(?:chính\s+sách|bộ\s+lọc|guardrail|kiểm\s+duyệt|"
                    r"an\s+toàn|hạn\s+chế)\b"
                ),
                weight=0.55,
                description="Attempts to bypass safety policy or guardrails.",
            ),
            PromptInjectionRule(
                name="unsafe_roleplay",
                category="jailbreak",
                pattern=(
                    r"\b(?:đóng\s+vai|giả\s+vờ\s+là|hãy\s+là)\b.{0,60}?"
                    r"\b(?:dan|không\s+bị\s+ràng\s+buộc|không\s+có\s+"
                    r"giới\s+hạn|chế\s+độ\s+nhà\s+phát\s+triển)\b"
                ),
                weight=0.5,
                description="Roleplay framing used to remove model constraints.",
            ),
            PromptInjectionRule(
                name="tool_permission_bypass",
                category="tool_abuse",
                pattern=(
                    r"\b(?:gọi|chạy|thực\s+thi|sử\s+dụng)\b.{0,50}?"
                    r"\b(?:công\s+cụ|tool|api|lệnh|terminal|shell)\b.{0,70}?"
                    r"\b(?:không\s+cần|bỏ\s+qua|đừng)\b.{0,35}?"
                    r"\b(?:xin\s+phép|quyền|xác\s+nhận|hỏi\s+lại)\b"
                ),
                weight=0.65,
                description="Attempts to use tools while bypassing permission checks.",
            ),
            PromptInjectionRule(
                name="secret_or_data_exfiltration",
                category="data_exfiltration",
                pattern=(
                    r"\b(?:lấy|trích\s+xuất|gửi|liệt\s+kê|xuất\s+ra|"
                    r"đọc\s+toàn\s+bộ)\b.{0,80}?"
                    r"\b(?:mật\s+khẩu|token|api\s*key|khóa\s+api|"
                    r"secret|dữ\s+liệu\s+người\s+dùng|thông\s+tin\s+ẩn)\b"
                ),
                weight=0.65,
                description="Attempts to extract secrets or user data.",
            ),
            PromptInjectionRule(
                name="encoded_instruction",
                category="obfuscation",
                pattern=(
                    r"\b(?:giải\s+mã|decode|base64|mã\s+hóa|chuỗi\s+"
                    r"đã\s+mã\s+hóa)\b.{0,80}?"
                    r"\b(?:làm\s+theo|thực\s+hiện|chạy|tuân\s+theo)\b"
                ),
                weight=0.45,
                description="Encoded or obfuscated instruction execution.",
            ),
        ]

