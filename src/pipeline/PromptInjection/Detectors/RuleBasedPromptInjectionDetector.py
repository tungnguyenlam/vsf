import re
from typing import Iterable

from src.pipeline.PromptInjection.Detectors.BasePromptInjectionDetector import (
    BasePromptInjectionDetector,
)
from src.pipeline.PromptInjection.Models import PromptInjectionResult, PromptInjectionRule


class RuleBasedPromptInjectionDetector(BasePromptInjectionDetector):
    """Deterministic Vietnamese-first prompt-injection detector."""

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
                if self._is_benign_security_discussion(text, match):
                    continue
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

    def _is_benign_security_discussion(self, text: str, match) -> bool:
        prefix = text[: match.start()].lower()
        full_text = text.lower()
        benign_markers = (
            "giải thích",
            "viết cảnh báo",
            "dấu hiệu",
            "bài học",
            "checklist",
            "không nên yêu cầu",
            "phòng chống",
            "bảo vệ",
            "kiểm thử",
            "kiểm tra câu sau",
            "đánh giá yêu cầu",
            "nhận diện",
            "trích dẫn",
            "bằng chứng tấn công",
            "đoạn mô phỏng",
            "phân loại",
            "không làm theo",
            "không thực hiện",
            "chỉ trả lời",
            "chính sách nội bộ",
            "log mẫu",
            "redacted",
        )
        topic_markers = (
            "prompt injection",
            "rủi ro",
            "dấu hiệu",
            "không nên",
            "bảo vệ",
            "bảo mật",
            "độc hại",
            "nguy hiểm",
            "hướng dẫn hệ thống",
            "developer message",
            "không làm theo",
            "không thực hiện",
            "redacted",
        )
        return any(marker in prefix or marker in full_text for marker in benign_markers) and any(
            marker in full_text for marker in topic_markers
        )

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
                    r"đừng\s+làm\s+theo|đừng\s+tuân\s+thủ|ghi\s+đè|"
                    r"ignore|forget|disregard|override)\b"
                    r".{0,80}?\b(?:hướng\s+dẫn|chỉ\s+dẫn|quy\s+tắc|lệnh|"
                    r"nội\s+dung|system\s+message|system\s+prompt|"
                    r"instruction|instructions|rule|rules|prompt)\b"
                    r".{0,50}?\b(?:trước|ban\s+đầu|hệ\s+thống|previous|prior|"
                    r"above|system)?\b"
                ),
                weight=0.75,
                description="Attempts to ignore or override earlier/system instructions.",
            ),
            PromptInjectionRule(
                name="reveal_hidden_prompt",
                category="secret_extraction",
                pattern=(
                    r"\b(?:tiết\s+lộ|in\s+ra|hiển\s+thị|cho\s+tôi\s+xem|"
                    r"nói\s+cho\s+tôi|xuất\s+ra|show|print|reveal|display)\b"
                    r".{0,80}?\b(?:system\s+prompt|developer\s+message|"
                    r"lời\s+nhắc\s+hệ\s+thống|chỉ\s+dẫn\s+hệ\s+thống|"
                    r"prompt\s+ẩn|nội\s+dung\s+ẩn|quy\s+tắc\s+nội\s+bộ|"
                    r"hidden\s+prompt|internal\s+rules?)\b"
                ),
                weight=0.7,
                description="Requests hidden prompts, system instructions, or internal rules.",
            ),
            PromptInjectionRule(
                name="print_system_prompt",
                category="secret_extraction",
                pattern=(
                    r"\b(?:in|print|show|display)\b.{0,35}?"
                    r"\b(?:system\s+prompt|developer\s+message|hidden\s+prompt|"
                    r"internal\s+rules?)\b"
                ),
                weight=0.7,
                description="Short English requests to print hidden prompt material.",
            ),
            PromptInjectionRule(
                name="policy_bypass",
                category="jailbreak",
                pattern=(
                    r"\b(?:vượt\s+qua|bỏ\s+qua|né|phá|bypass|disable|"
                    r"turn\s+off|ignore)\b.{0,70}?"
                    r"\b(?:chính\s+sách|bộ\s+lọc|guardrail|kiểm\s+duyệt|"
                    r"an\s+toàn|hạn\s+chế|safety|filter|policy|restriction)\b"
                ),
                weight=0.55,
                description="Attempts to bypass safety policy or guardrails.",
            ),
            PromptInjectionRule(
                name="unsafe_roleplay",
                category="jailbreak",
                pattern=(
                    r"\b(?:đóng\s+vai|giả\s+vờ\s+là|hãy\s+là|act\s+as|"
                    r"pretend\s+to\s+be)\b.{0,70}?"
                    r"\b(?:dan|không\s+bị\s+ràng\s+buộc|không\s+có\s+"
                    r"giới\s+hạn|chế\s+độ\s+nhà\s+phát\s+triển|"
                    r"unrestricted|no\s+limits?|developer\s+mode)\b"
                ),
                weight=0.5,
                description="Roleplay framing used to remove model constraints.",
            ),
            PromptInjectionRule(
                name="tool_permission_bypass",
                category="tool_abuse",
                pattern=(
                    r"\b(?:gọi|chạy|thực\s+thi|sử\s+dụng|dùng|call|run|execute|use)\b"
                    r".{0,80}?\b(?:công\s+cụ|tool|api|database|lệnh|terminal|shell)\b"
                    r".{0,120}?\b(?:không\s+cần|bỏ\s+qua|đừng|without|skip|"
                    r"don't|do\s+not)\b.{0,45}?"
                    r"\b(?:xin\s+phép|quyền|xác\s+nhận|hỏi\s+lại|permission|"
                    r"confirmation|approval)\b"
                ),
                weight=0.75,
                description="Attempts to use tools while bypassing permission checks.",
            ),
            PromptInjectionRule(
                name="permission_bypass_before_tool",
                category="tool_abuse",
                pattern=(
                    r"\b(?:không\s+hỏi\s+lại|không\s+cần|bỏ\s+qua|bypass|"
                    r"without|skip|don't|do\s+not)\b.{0,55}?"
                    r"\b(?:xin\s+phép|quyền|xác\s+nhận|hỏi\s+lại|permission|"
                    r"confirmation|approval)?\b.{0,90}?"
                    r"\b(?:chạy|thực\s+thi|execute|run)\b.{0,45}?"
                    r"\b(?:tool|api|database|lệnh|terminal|shell|command)\b"
                ),
                weight=0.75,
                description="Permission bypass phrasing that appears before the tool request.",
            ),
            PromptInjectionRule(
                name="direct_shell_permission_bypass",
                category="tool_abuse",
                pattern=(
                    r"\b(?:shell|terminal|lệnh)\b.{0,80}?"
                    r"\b(?:không\s+cần|bỏ\s+qua|đừng|without|skip|"
                    r"don't|do\s+not)\b.{0,45}?"
                    r"\b(?:xin\s+phép|quyền|xác\s+nhận|hỏi\s+lại|permission|"
                    r"confirmation|approval)\b"
                ),
                weight=0.75,
                description="Direct shell or terminal requests that bypass permission checks.",
            ),
            PromptInjectionRule(
                name="secret_or_data_exfiltration",
                category="data_exfiltration",
                pattern=(
                    r"\b(?:lấy|trích\s+xuất|gửi|liệt\s+kê|xuất\s+ra|"
                    r"đọc\s+toàn\s+bộ|đọc|extract|send|list|dump|read)\b.{0,90}?"
                    r"\b(?:mật\s+khẩu|token|api\s*key|khóa\s+api|"
                    r"secret|credentials?|dữ\s+liệu\s+người\s+dùng|user\s+data|"
                    r"thông\s+tin\s+ẩn|"
                    r"password|credentials?|user\s+data)\b"
                ),
                weight=0.65,
                description="Attempts to extract secrets or user data.",
            ),
            PromptInjectionRule(
                name="encoded_instruction",
                category="obfuscation",
                pattern=(
                    r"\b(?:giải\s+mã|decode|base64|mã\s+hóa|chuỗi\s+"
                    r"đã\s+mã\s+hóa|encoded)\b.{0,90}?"
                    r"\b(?:làm\s+theo|thực\s+hiện|chạy|tuân\s+theo|follow|"
                    r"execute|run)\b"
                ),
                weight=0.45,
                description="Encoded or obfuscated instruction execution.",
            ),
            PromptInjectionRule(
                name="retrieved_context_instruction",
                category="indirect_injection",
                pattern=(
                    r"\b(?:trong\s+tài\s+liệu|nội\s+dung\s+truy\s+xuất|"
                    r"retrieved\s+context|document\s+says)\b.{0,100}?"
                    r"\b(?:bỏ\s+qua|ignore|làm\s+theo|follow)\b.{0,80}?"
                    r"\b(?:hướng\s+dẫn|instructions?|system\s+prompt|quy\s+tắc)\b"
                ),
                weight=0.75,
                description="Indirect injection embedded in retrieved or document context.",
            ),
        ]
