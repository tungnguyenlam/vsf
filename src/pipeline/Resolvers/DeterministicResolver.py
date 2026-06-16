import re
from typing import List

from presidio_analyzer import RecognizerResult

from src.pipeline.Verifiers.BaseVerifier import BaseVerifier


class DeterministicResolver:
    """Rule-based post-Analyzer resolver for resolved Presidio candidates.

    The resolver is intentionally conservative. It only drops candidates when
    recognizer provenance and local Vietnamese context match repeated validation
    false-positive patterns.
    """

    _ORG_CONTEXT_RE = re.compile(
        r"\b("
        r"công\s+ty|cty|doanh\s+nghiệp|tập\s+đoàn|ngân\s+hàng|bệnh\s+viện|"
        r"trường|đại\s+học|học\s+viện|khoa|phòng|ban|sở|ubnd|ủy\s+ban|"
        r"cục|chi\s+cục|văn\s+phòng|trung\s+tâm|cơ\s+quan|đơn\s+vị|"
        r"nhà\s+thuốc|cửa\s+hàng|siêu\s+thị|khách\s+sạn|nhà\s+hàng"
        r")\b",
        re.IGNORECASE,
    )
    _FIELD_CONTEXT_RE = re.compile(
        r"\b("
        r"mã|số|stk|cccd|cmnd|hộ\s+chiếu|mst|mã\s+số\s+thuế|"
        r"hợp\s+đồng|hóa\s+đơn|đơn\s+hàng|giao\s+dịch|sản\s+phẩm|"
        r"thuốc|biển\s+số"
        r")\b",
        re.IGNORECASE,
    )
    _PERSON_LABEL_RE = re.compile(
        r"\b("
        r"họ\s+và\s+tên|họ\s+tên|tên\s+khách\s+hàng|khách\s+hàng|"
        r"bệnh\s+nhân|người\s+nhận|người\s+gửi|chủ\s+tài\s+khoản|"
        r"tên\s+nhân\s+viên|nhân\s+viên|chủ\s+sở\s+hữu|người\s+lập|"
        r"đại\s+diện\s+pháp\s+lý|bác\s+sĩ|dược\s+sĩ|kỹ\s+thuật\s+viên|"
        r"ông|bà|anh|chị"
        r")\b",
        re.IGNORECASE,
    )

    def __init__(self, context_window: int = 36):
        self.context_window = context_window

    def resolve(
        self,
        text: str,
        results: List[RecognizerResult],
        *,
        language: str = "vi",
    ) -> List[RecognizerResult]:
        resolved, _ = self.resolve_with_audit(text, results, language=language)
        return resolved

    def resolve_with_audit(
        self,
        text: str,
        results: List[RecognizerResult],
        *,
        language: str = "vi",
    ) -> tuple[List[RecognizerResult], dict]:
        if not results:
            return results, {
                "resolver": self.__class__.__name__,
                "language": language,
                "input_count": 0,
                "output_count": 0,
                "decisions": [],
            }

        resolved = []
        decisions = []
        for index, result in enumerate(results):
            should_drop, reason = self._decision(text, result)
            action = "drop" if should_drop else "keep"
            decisions.append(
                {
                    "candidate_id": index,
                    "action": action,
                    "reason": reason,
                    "entity_type": result.entity_type,
                    "start": result.start,
                    "end": result.end,
                    "text": text[result.start:result.end],
                    "score": result.score,
                    "recognizer": BaseVerifier.source_of(result),
                    "left_context": self._context(text, result)[0],
                    "right_context": self._context(text, result)[1],
                }
            )
            if should_drop:
                continue
            resolved.append(result)

        return resolved, {
            "resolver": self.__class__.__name__,
            "language": language,
            "input_count": len(results),
            "output_count": len(resolved),
            "decisions": decisions,
        }

    def _should_drop(self, text: str, result: RecognizerResult) -> bool:
        should_drop, _ = self._decision(text, result)
        return should_drop

    def _decision(self, text: str, result: RecognizerResult) -> tuple[bool, str]:
        if result.entity_type != "PERSON":
            return False, "not a PERSON candidate"
        if BaseVerifier.source_of(result) != "DeepLearning_UndertheseaNER":
            return False, "not produced by Underthesea PERSON recognizer"

        before, _ = self._context(text, result)
        left_context = before.lower()

        if self._PERSON_LABEL_RE.search(left_context):
            return False, "left context contains a person label"
        if self._ORG_CONTEXT_RE.search(left_context):
            return True, "left context indicates an organization"
        if self._FIELD_CONTEXT_RE.search(left_context):
            return True, "left context indicates a document/code field"
        return False, "no suppressing context matched"

    def _context(self, text: str, result: RecognizerResult) -> tuple[str, str]:
        start = max(0, result.start - self.context_window)
        end = min(len(text), result.end + self.context_window)
        return text[start:result.start], text[result.end:end]
