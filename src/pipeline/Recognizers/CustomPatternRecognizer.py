import re
from dataclasses import dataclass
from typing import Iterable, List

from presidio_analyzer import AnalysisExplanation, EntityRecognizer, RecognizerResult

from src.pipeline.Recognizers.BaseRecognizer import BaseRecognizer


@dataclass(frozen=True)
class ContextRegexPattern:
    name: str
    entity_type: str
    regex: str
    score: float
    ignore_case: bool = True


class VietnameseContextRegexRecognizer(EntityRecognizer):
    """High-precision Vietnamese regex recognizer with value-only spans."""

    VALUE_GROUP = "value"

    def __init__(self, patterns: Iterable[ContextRegexPattern]):
        self.patterns = list(patterns)
        super().__init__(
            supported_entities=sorted({pattern.entity_type for pattern in self.patterns}),
            supported_language="vi",
            name="VietnameseContextRegexRecognizer",
        )

    def load(self) -> None:
        return None

    def analyze(self, text, entities, nlp_artifacts):
        requested = set(entities or self.supported_entities)
        results: List[RecognizerResult] = []
        for pattern in self.patterns:
            if pattern.entity_type not in requested:
                continue
            flags = re.UNICODE
            if pattern.ignore_case:
                flags |= re.IGNORECASE
            for match in re.finditer(pattern.regex, text, flags=flags):
                start, end = self._value_span(match)
                if start == end:
                    continue
                results.append(
                    RecognizerResult(
                        entity_type=pattern.entity_type,
                        start=start,
                        end=end,
                        score=pattern.score,
                        analysis_explanation=AnalysisExplanation(
                            recognizer=self.name,
                            original_score=pattern.score,
                            pattern_name=pattern.name,
                            pattern=pattern.regex,
                            textual_explanation=f"Matched {pattern.name}",
                            regex_flags=flags,
                        ),
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                        },
                    )
                )
        return results

    def _value_span(self, match):
        try:
            return match.span(self.VALUE_GROUP)
        except IndexError:
            return match.span()


class CustomPatternRecognizer(BaseRecognizer):
    """Wrapper for high-precision Vietnamese regex recognizers."""

    def __init__(self, device: str = "cpu", verbose: bool = False):
        super().__init__(device=device, verbose=verbose)
        self.recognizers = []

    def build_patterns(self) -> list:
        patterns = [
            ContextRegexPattern(
                name="email",
                entity_type="EMAIL_ADDRESS",
                regex=r"(?P<value>\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)",
                score=0.95,
            ),
            ContextRegexPattern(
                name="vn_mobile_phone",
                entity_type="PHONE_NUMBER",
                regex=(
                    r"(?<!\d)(?P<value>(?:\+?84|0)[ .-]?[35789]"
                    r"(?:[ .-]?\d){8})(?!\d)"
                ),
                score=0.85,
            ),
            ContextRegexPattern(
                name="vn_cccd_cmnd",
                entity_type="ID",
                regex=(
                    r"(?:số\s*)?(?:cccd|cmnd|cmtnd|căn\s*cước(?:\s*công\s*dân)?|"
                    r"chứng\s*minh(?:\s*nhân\s*dân)?|thẻ\s*cccd)"
                    r"(?:\s*/\s*(?:cmnd|hc|thẻ\s*cccd))*\s*[:*]?\s*"
                    r"(?P<value>\d{12}|\d{9})"
                ),
                score=0.9,
            ),
            ContextRegexPattern(
                name="vn_tax_id",
                entity_type="ID",
                regex=r"mã\s*số\s*thuế\s*[:*]?\s*(?P<value>\d{10}(?:-\d{3})?)",
                score=0.88,
            ),
            ContextRegexPattern(
                name="vn_employee_id",
                entity_type="ID",
                regex=(
                    r"mã\s*nhân\s*viên\s*[:*]?\s*"
                    r"(?P<value>(?:[A-Z]{1,4}\d{4,8})|(?:\d{6,12}))"
                ),
                score=0.82,
            ),
            ContextRegexPattern(
                name="vn_passport_id",
                entity_type="ID",
                regex=(
                    r"(?:hộ\s*chiếu|passport)(?:\s*số)?\s*[:*]?\s*"
                    r"(?P<value>[A-Z]\d{6,8})"
                ),
                score=0.84,
            ),
            ContextRegexPattern(
                name="vn_transaction_id",
                entity_type="ID",
                regex=(
                    r"mã\s*giao\s*dịch(?:\s+(?:mới\s+nhất|ngoại\s+tệ|"
                    r"nghi\s+vấn|cổ\s+tức))?\s*[:*]?\s*"
                    r"(?P<value>[A-Z]{2,}\d[A-Z0-9]{4,20}|\d{10,18})"
                ),
                score=0.8,
            ),
            ContextRegexPattern(
                name="vn_context_date",
                entity_type="DATE_TIME",
                regex=(
                    r"(?:ngày\s+(?!cấp\b)(?:sinh|họp|đào\s*tạo|hoàn\s*thành|"
                    r"làm\s*việc|phỏng\s*vấn|gửi|tiếp\s*nhận|đăng\s*ký|"
                    r"hiệu\s*lực|ký|khám|điều\s*trị)|thời\s*điểm\s*ghi\s*nhận)"
                    r"\s*[:*]?\s*(?P<value>\d{1,2}/\d{1,2}/\d{4})"
                ),
                score=0.82,
            ),
            ContextRegexPattern(
                name="vn_birth_year",
                entity_type="DATE_TIME",
                regex=r"năm\s*sinh\s*[:*]?\s*(?P<value>(?:19|20)\d{2})",
                score=0.78,
            ),
            ContextRegexPattern(
                name="vn_birth_month",
                entity_type="DATE_TIME",
                regex=r"tháng\s*sinh\s*[:*]?\s*(?P<value>0?[1-9]|1[0-2])\b",
                score=0.78,
            ),
            ContextRegexPattern(
                name="vn_house_number",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>Số\s+\d+[A-Z]?)\b"
                    r"(?=,?\s+(?:Đường|Phố|Ngõ|Ấp|Buôn|Bản|Xóm|"
                    r"Phường|Xã|Huyện|Quận|Thị xã|Thành phố|Tỉnh|TP\.))"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_street_like_location",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>(?:Đường|Phố|Ngõ|Ấp|Buôn|Bản|Xóm)\s+"
                    r"[A-ZÀ-Ỹ0-9][^,.;:\n]{0,45}?)"
                    r"(?=\s+(?:Phường|Xã|Huyện|Quận|Thị\s*xã|Thành\s*phố|"
                    r"Tỉnh|TP\.|Tên|Mã|Ngày|Số|Địa|$)|[,.;:\n]|$)"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_ward_location",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>(?:Phường|Xã)\s+[A-ZÀ-Ỹ0-9][^,.;:\n]{0,40}?)"
                    r"(?=\s+(?:Huyện|Quận|Thị\s*xã|Thành\s*phố|Tỉnh|TP\.|"
                    r"Tên|Mã|Ngày|Số|Địa|$)|[,.;:\n]|$)"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_district_location",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>(?:Huyện|Quận|Thị\s*xã|Thành\s*phố)\s+"
                    r"[A-ZÀ-Ỹ0-9][^,.;:\n]{0,40}?)"
                    r"(?=\s+(?:Tỉnh|TP\.|Tên|Mã|Ngày|Số|Địa|$)|[,.;:\n]|$)"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_province_location",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>(?:Tỉnh|TP\.)\s+[A-ZÀ-Ỹ0-9][^,.;:\n]{0,40}?)"
                    r"(?=\s+(?:Tên|Mã|Ngày|Số|Địa|Email|Liên|$)|[,.;:\n]|$)"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_labeled_name",
                entity_type="PERSON",
                regex=(
                    r"(?:Họ\s+và\s+tên(?:\s+(?:chủ\s+thuê\s+bao|chủ\s+xe|"
                    r"nhân\s+viên|đầy\s+đủ))?|Tên\s+(?:nhân\s+viên|ứng\s+viên|"
                    r"học\s+viên|chủ\s+hộ|người\s+nộp\s+thuế|trẻ\s+sơ\s+sinh)|"
                    r"Bệnh\s+nhân|Người\s+đánh\s+giá|Người\s+ghi\s+biên\s+bản|"
                    r"Nhân\s+viên\s+phụ\s+trách)"
                    r"\s*[:*]\s*(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*(?:\s+"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*){1,5})"
                    r"(?=\s+(?:Mã|Ngày|Giới|Số|Học|Chức|Lĩnh|Địa|Quốc|"
                    r"Nhà|Trình|Tuổi|Bệnh|Tình|$))"
                ),
                score=0.8,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_organization_labeled",
                entity_type="ORGANIZATION",
                regex=(
                    r"(?:Tên\s+(?:tổ\s+chức|đơn\s+vị|ngân\s+hàng)(?:\s+"
                    r"(?:đào\s+tạo|tuyển\s+dụng|xác\s+nhận|phát\s+hành|"
                    r"bảo\s+lãnh))?|Đơn\s+vị\s+công\s+tác|Bệnh\s+viện(?:\s+"
                    r"(?:điều\s+trị|thực\s+hiện))?|Bank)"
                    r"\s*[:*]?\s*(?P<value>[A-ZÀ-Ỹ][^:\n]{1,90}?)"
                    r"(?=\s+(?:Loại|Địa|Ngày|Lĩnh|Mã|Hạn|SWIFT|BIC|Số|"
                    r"Nội|Giá|Xếp|Chẩn|Bác|Tỉnh|$))"
                ),
                score=0.78,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_bank_account",
                entity_type="BANK_ACCOUNT",
                regex=(
                    r"(?:số\s*tài\s*khoản|stk|"
                    r"tài\s*khoản\s+(?:người\s+(?:hưởng|ra\s+lệnh)|"
                    r"giao\s+dịch|lưu\s+ký|mở\s+mới|doanh\s+nghiệp|"
                    r"nhận\s+cổ\s+tức|nhận|chuyển|thanh\s+toán))"
                    r"\s*[:*]?\s*(?P<value>\d(?:[ -]?\d){7,18})"
                ),
                score=0.86,
            ),
        ]
        return [VietnameseContextRegexRecognizer(patterns)]

    def load_model(self):
        if not self.recognizers:
            self.recognizers = self.build_patterns()
            self.model = self.recognizers

    def unload_model(self):
        self.recognizers = []
        super().unload_model()

    def register_to_analyzer(self, analyzer_engine):
        self.load_model()
        for recognizer in self.recognizers:
            analyzer_engine.registry.add_recognizer(recognizer)

    def predict(self, inputs, **kwargs):
        return []
