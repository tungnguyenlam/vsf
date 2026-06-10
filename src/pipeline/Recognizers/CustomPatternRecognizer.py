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

    def __init__(
        self,
        device: str = "cpu",
        verbose: bool = False,
        recall_mode: bool = False,
    ):
        super().__init__(device=device, verbose=verbose)
        self.recognizers = []
        self.recall_mode = recall_mode

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
                    r"(?:\s*/\s*(?:cmnd|hc|id\s*no|thẻ\s*cccd))*\s*[:*]?\s*"
                    r"(?P<value>\d{12}|\d{9})"
                ),
                score=0.9,
            ),
            ContextRegexPattern(
                name="vn_cccd_loose_number",
                entity_type="ID",
                regex=(
                    r"(?:loại\s*[:*]?\s*cccd\b.{0,30}?số\s*[:*]?\s*)"
                    r"(?P<value>\d{12}|\d{9})"
                ),
                score=0.86,
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
                    r"(?P<value>(?:[A-Z]{1,4}-\d{4}-\d{3,6})|"
                    r"(?:[A-Z]{1,4}\d{4,8})|(?:\d{6,12}))"
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
                    r"nghi\s+vấn|cổ\s+tức|lưu\s+ký|thanh\s+toán))?\s*[:*]?\s*"
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
                    r"hiệu\s*lực|ký|khám(?:\s+gần\s+nhất)?|điều\s*trị|"
                    r"sao\s*kê|ghi\s*nhận|đánh\s*giá|phỏng\s*vấn\s+nâng\s*cao|"
                    r"hoàn\s*thành\s*khóa\s*học|kết\s*thúc\s*công\s*việc)|"
                    r"ngày\s*/\s*date|"
                    r"thời\s*điểm\s*ghi\s*nhận)"
                    r"\s*[:*]?\s*(?P<value>\d{1,2}/\d{1,2}/\d{4})"
                ),
                score=0.82,
            ),
            ContextRegexPattern(
                name="vn_context_year",
                entity_type="DATE_TIME",
                regex=(
                    r"(?:năm\s*tài\s*chính|cho\s+năm|của\s+năm|"
                    r"báo\s*cáo\s+tổng\s*hợp\s+năm)\s*"
                    r"(?P<value>(?:19|20)\d{2})"
                ),
                score=0.76,
            ),
            ContextRegexPattern(
                name="vn_context_month_duration",
                entity_type="DATE_TIME",
                regex=(
                    r"(?:sao\s*kê\s+tối\s*thiểu|trong\s+vòng|trong\s+khoảng|"
                    r"dữ\s*liệu\s+trong)\s*"
                    r"(?P<value>0?[1-9]|1[0-2])\s*tháng"
                ),
                score=0.72,
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
                    r"(?=,?\s+(?:Đường|Phố|Ngõ|Ấp|Buôn|Bản|Xóm|Thôn|"
                    r"Phường|Xã|Huyện|Quận|Thị xã|Thành phố|Tỉnh|TP\.))"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_street_like_location",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>(?:Đường|Phố|Ngõ|Ấp|Buôn|Bản|Xóm|Thôn)\s+"
                    r"(?!(?:Mã|Ngày|Số|Tên|Địa)\b)[A-ZÀ-Ỹ0-9][^,.;:\n]{0,45}?)"
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
                    r"(?<!Công an )(?P<value>(?:Huyện|Quận|Thị\s*xã|Thành\s*phố)\s+"
                    r"[A-ZÀ-Ỹ0-9](?:(?!\s+ngày\s+cấp\b)[^,.;:\n]){0,40}?)"
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
                    r"(?=\s+(?:Tên|Mã|Ngày|Số|Địa|Email|Liên|Cán\s*bộ|"
                    r"Thông\s*tin|Tọa\s*độ|$)|[,.;:\n]|$)"
                ),
                score=0.74,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="country_after_vn_address",
                entity_type="LOCATION",
                regex=(
                    r"(?:Tỉnh|TP\.)\s+[A-ZÀ-Ỹ0-9][^,.;:\n]{0,40},\s*"
                    r"(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]*(?:\s+(?:và\s+)?"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]*){0,4})"
                    r"(?=\s+(?:Thông\s*tin|Tọa\s*độ|Số\s*điện|Email|$))"
                ),
                score=0.7,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_labeled_name",
                entity_type="PERSON",
                regex=(
                    r"(?:Họ\s+và\s+tên(?:\s+(?:chủ\s+thuê\s+bao|chủ\s+xe|"
                    r"nhân\s+viên|ứng\s+viên|đầy\s+đủ))?|Tên\s+(?:nhân\s+viên|ứng\s+viên|"
                    r"học\s+viên|chủ\s+hộ|người\s+nộp\s+thuế|trẻ\s+sơ\s+sinh)|"
                    r"Bệnh\s+nhân|Bác\s+sĩ\s+chuyên\s+môn|"
                    r"Người\s+đánh\s+giá|Người\s+ghi\s+biên\s+bản|"
                    r"Nhân\s+viên\s+phụ\s+trách)"
                    r"\s*[:*]\s*(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*(?:\s+"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*){1,5})"
                    r"(?=\s+(?:Mã|Ngày|Giới|Số|Học|Chức|Lĩnh|Địa|Quốc|"
                    r"Nhà|Trình|Tuổi|Bệnh|Tình|Vị|$)|$)"
                ),
                score=0.8,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_split_surname",
                entity_type="PERSON",
                regex=(
                    r"\bHọ\s*[:*]\s*(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]{1,20})"
                    r"(?=\s+Tên\s*[:*])"
                ),
                score=0.72,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_split_given_name",
                entity_type="PERSON",
                regex=(
                    r"\bTên\s*[:*]\s*(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*(?:\s+"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*){0,3})"
                    r"(?=\s+(?:Họ\s+và\s+tên|Giới|Ngày|Mã|Số|Địa|$))"
                ),
                score=0.72,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_honorific_narrative",
                entity_type="PERSON",
                regex=(
                    r"\b(?:Ông|Bà)\s+(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*"
                    r"(?:\s+[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*){1,3})"
                    r"(?=\s+(?:đã|xác|thực|người|nhận|cung|tiến|yêu))"
                ),
                score=0.7,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_honorific_surname",
                entity_type="PERSON",
                regex=(
                    r"\b(?:Ông|Bà)\s+(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]{1,20})"
                    r"(?=\s+[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’])"
                ),
                score=0.68,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_person_honorific_given_name",
                entity_type="PERSON",
                regex=(
                    r"\b(?:Ông|Bà)\s+[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]{1,20}\s+"
                    r"(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*(?:\s+"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*){0,2})"
                    r"(?=\s+(?:đã|xác|thực|người|nhận|cung|tiến|yêu|"
                    r"đăng|làm|vừa))"
                ),
                score=0.68,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="vn_organization_labeled",
                entity_type="ORGANIZATION",
                regex=(
                    r"(?:Tên\s+(?:tổ\s+chức|đơn\s+vị|ngân\s+hàng|cửa\s+hàng)"
                    r"(?:\s+(?:đào\s+tạo|tuyển\s+dụng|xác\s+nhận|phát\s+hành|"
                    r"bảo\s+lãnh|vận\s+tải|thực\s+hiện))?|"
                    r"Đơn\s+vị\s+(?:công\s+tác|làm\s+việc\s+gần\s+nhất)|"
                    r"Tại\s+Ngân\s+hàng\s*/\s*At\s+Bank|Bệnh\s+viện(?:\s+"
                    r"(?:điều\s+trị|thực\s+hiện))?|Bank)"
                    r"\s*[:*]?\s*(?P<value>[A-ZÀ-Ỹ][^:\n]{1,90}?)"
                    r"(?=\s+(?:Loại|Địa|Ngày|Lĩnh|Mã|Hạn|SWIFT|BIC|Số|"
                    r"Nội|Giá|Xếp|Chẩn|Bác|Tỉnh|Kho|Kế|Vị|I\.|$))"
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
                    r"nhận\s+cổ\s+tức|nhận|chuyển|thanh\s+toán)|"
                    r"(?:dr\s+)?a/c\s+no(?:\s*/\s*serial)?)"
                    r"\s*[:*]?\s*(?P<value>\d(?:[ -]?\d){7,18})"
                ),
                score=0.86,
            ),
        ]
        if self.recall_mode:
            patterns.extend(self.build_recall_patterns())
        return [VietnameseContextRegexRecognizer(patterns)]

    def build_recall_patterns(self) -> list:
        """Broader context patterns for recall-oriented experiments."""
        return [
            ContextRegexPattern(
                name="recall_person_labeled_roles",
                entity_type="PERSON",
                regex=(
                    r"(?:Người\s+(?:phụ\s+trách|gửi\s+ticket|nhận|giao\s+tiền|"
                    r"yêu\s+cầu)|Tên\s+(?:người\s+yêu\s+cầu|bệnh\s+nhân|"
                    r"sản\s+phụ|trưởng\s+nhóm|tài\s+khoản\s+trích\s+nợ)|"
                    r"Nhân\s*viên|Đại\s*diện\s*[:*]?\s*Ông/bà|"
                    r"Bác\s+sĩ(?:\s+(?:kê\s+đơn|ICU\s+phụ\s+trách|"
                    r"cấp\s+cứu|sản\s+khoa|ký\s+xác\s+nhận))?|"
                    r"Cash\s*receiver|Delivered\s*by|Dr\s*A/C\s*name|"
                    r"Signature\s*&\s*full\s*name)"
                    r"\s*[:*]?\s*(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*(?:\s+"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ'’]*){1,5})"
                    r"(?=\s+(?:Mã|Ngày|Email|Số|Địa|Chức|Vị|Lĩnh|Bệnh|"
                    r"Tình|Nhiệm|Quá|Người|Tại|$)|$)"
                ),
                score=0.62,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="recall_date_labeled",
                entity_type="DATE_TIME",
                regex=(
                    r"ngày\s+(?!(?:cấp|cấp\s+đơn|hết\s+hạn)\b)[^0-9:\n]{0,45}?[:*]?\s*"
                    r"(?P<value>\d{1,2}/\d{1,2}/\d{4})"
                ),
                score=0.65,
            ),
            ContextRegexPattern(
                name="recall_date_today_clause",
                entity_type="DATE_TIME",
                regex=r"hôm\s+nay,\s*ngày\s+(?P<value>\d{1,2}/\d{1,2}/\d{4})",
                score=0.65,
            ),
            ContextRegexPattern(
                name="recall_context_year",
                entity_type="DATE_TIME",
                regex=(
                    r"(?:chuẩn\s+năm|tổng\s+hợp\s+năm|báo\s*cáo\s+năm|"
                    r"theo\s+năm|năm\s+tài\s+chính|cho\s+năm|của\s+năm)\s*"
                    r"(?P<value>(?:19|20)\d{2})"
                ),
                score=0.58,
            ),
            ContextRegexPattern(
                name="recall_context_month_duration",
                entity_type="DATE_TIME",
                regex=(
                    r"(?:thời\s*gian\s+sao\s*kê|sao\s*kê|trong\s+vòng|"
                    r"trong\s+khoảng|dữ\s*liệu\s+trong)\s*"
                    r"(?P<value>0?[1-9]|1[0-2])\s*tháng"
                ),
                score=0.58,
            ),
            ContextRegexPattern(
                name="recall_organization_labeled",
                entity_type="ORGANIZATION",
                regex=(
                    r"(?:Tên\s+(?:tổ\s+chức|ngân\s+hàng|công\s+ty|kho|"
                    r"doanh\s+nghiệp|đơn\s+vị)"
                    r"(?:\s+[A-Za-zÀ-ỹ/()]+){0,6}|Tổ\s*chức|"
                    r"Tên\s+công\s+ty|Kính\s+gửi|Chi\s+nhánh/Phòng\s+Giao\s+Dịch|"
                    r"Bên\s+(?:bảo\s+đảm|được\s+bảo\s+đảm))"
                    r"\s*[:*]?\s*(?P<value>[A-ZÀ-Ỹ][^:\n]{1,100}?)"
                    r"(?=\s+(?:Loại|Tổ|Số|Ngày|Địa|Mã|Lĩnh|Nội|Chức|"
                    r"Chi\s+nhánh|Kho|Vị|$))"
                ),
                score=0.6,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="recall_employee_id",
                entity_type="ID",
                regex=(
                    r"mã\s*nhân\s*viên\s*[:*]?\s*"
                    r"(?P<value>(?:[A-Z&]{1,5}-\d{4}-\d{3,6})|"
                    r"(?:[A-Z]{2,5}-EMP-\d{4,8})|"
                    r"(?:[A-Z]{2,5}-\d{4,8})|(?:20\d{2}-\d{4,8}))"
                ),
                score=0.7,
            ),
            ContextRegexPattern(
                name="recall_transaction_id",
                entity_type="ID",
                regex=(
                    r"mã\s*giao\s*dịch(?:\s+[A-Za-zÀ-ỹ]+){0,4}\s*[:*]?\s*"
                    r"(?P<value>[A-Z]{2,}\d?[A-Z0-9]{6,24}|\d{10,18})"
                ),
                score=0.68,
            ),
            ContextRegexPattern(
                name="recall_business_tax_id",
                entity_type="ID",
                regex=(
                    r"(?:mã\s*số\s*(?:doanh\s*nghiệp|thuế(?:\s+hộ\s+kinh\s+doanh)?)|"
                    r"ĐKDN/ĐKKD/QĐTL\s+số)"
                    r"\s*[:*]?\s*(?P<value>\d{10}(?:-\d{3})?)"
                ),
                score=0.68,
            ),
            ContextRegexPattern(
                name="recall_document_number",
                entity_type="ID",
                regex=(
                    r"(?:CMND/CCCD\s*Số|Căn\s*cước\s*công\s*dân\s*số|"
                    r"Số\s+GTTT|Số\s+Thẻ\s+CCCD\s*/HC/\s*/Giấy\s+tờ\s+khác|"
                    r"Số\s+hộ\s*chiếu|passport\s*number)"
                    r"\s*[:*]?\s*(?P<value>[A-Z]\d{6,8}|\d{9}|\d{12})"
                ),
                score=0.68,
            ),
            ContextRegexPattern(
                name="recall_bank_account",
                entity_type="BANK_ACCOUNT",
                regex=(
                    r"(?:tài\s*khoản\s+(?:công\s+ty\s+liên\s+kết|liên\s+kết|"
                    r"ví\s+liên\s+kết|tài\s+chính\s+liên\s+kết|chứng\s+khoán|"
                    r"giao\s+dịch\s+chứng\s+khoán|thanh\s+toán\s+số)|"
                    r"số\s+tài\s*khoản\s+(?:nhận\s+lương|người\s+nhận|"
                    r"liên\s+kết|tiết\s+kiệm)|số\s+ví\s+thanh\s+toán|"
                    r"ví\s+thanh\s+toán)"
                    r"\s*[:*]?\s*(?P<value>\d(?:[ -]?\d){7,18})"
                ),
                score=0.7,
            ),
            ContextRegexPattern(
                name="recall_country_labeled",
                entity_type="LOCATION",
                regex=(
                    r"(?:quốc\s*gia|country)\s*[:*]?\s*"
                    r"(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]*(?:\s+(?:và\s+)?"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]*){0,4}?)"
                    r"(?=\s+(?:Mã|Địa|Tổng|$)|[,.;:\n]|$)"
                ),
                score=0.58,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="recall_country_after_address",
                entity_type="LOCATION",
                regex=(
                    r"(?:Tỉnh|TP\.|Thành\s+phố)\s+[A-ZÀ-Ỹ0-9][^,.;:\n]{0,45},\s*"
                    r"(?P<value>[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]*(?:\s+(?:và\s+)?"
                    r"[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]*){0,4}?)"
                    r"(?=\s+(?:Mã|Tọa|Hướng|Điểm|Địa|$)|[,.;:\n]|$)"
                ),
                score=0.58,
                ignore_case=False,
            ),
            ContextRegexPattern(
                name="recall_special_ward",
                entity_type="LOCATION",
                regex=(
                    r"(?P<value>Đặc\s+khu\s+[A-ZÀ-Ỹ][^,.;:\n]{1,35}?)"
                    r"(?=\s+(?:Huyện|Tỉnh|Thành\s+phố|TP\.|$)|[,.;:\n]|$)"
                ),
                score=0.58,
                ignore_case=False,
            ),
        ]

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
