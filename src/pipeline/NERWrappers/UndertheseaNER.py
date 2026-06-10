from typing import List

from src.pipeline.NERWrappers.BaseNERWrapper import BaseNERWrapper


DEFAULT_UNDERTHESEA_LABEL_MAPPING = {
    "PER": "PERSON",
    "LOC": "LOCATION",
    "ORG": "ORGANIZATION",
}


class UndertheseaNER(BaseNERWrapper):
    """Underthesea NER wrapper for lightweight Vietnamese entity detection."""

    def __init__(
        self,
        label_mapping: dict = None,
        score: float = 0.5,
        person_context_required: bool = False,
        min_score: float = 0.58,
    ):
        self.label_mapping = label_mapping or DEFAULT_UNDERTHESEA_LABEL_MAPPING
        self.score = score
        self.person_context_required = person_context_required
        self.min_score = min_score
        self._ner = None

    def load(self):
        if self._ner is None:
            from underthesea import ner

            self._ner = ner

    def unload(self):
        self._ner = None

    @property
    def is_loaded(self) -> bool:
        return self._ner is not None

    def predict_entities(self, text: str) -> List[dict]:
        if self._ner is None:
            self.load()

        tagged_tokens = self._ner(text)
        spans = []
        search_start = 0
        current = None

        for token, _pos, _chunk, ner_tag in tagged_tokens:
            start = text.find(token, search_start)
            if start < 0:
                start = text.find(token)
            if start < 0:
                continue
            end = start + len(token)
            search_start = end

            prefix, raw_label = self._split_bio_tag(ner_tag)
            entity_type = self.label_mapping.get(raw_label)
            if prefix == "O" or entity_type is None:
                if current is not None:
                    spans.append(current)
                    current = None
                continue
            if not self._accept_candidate(text, token, start, end, entity_type):
                if current is not None:
                    spans.append(current)
                    current = None
                continue

            if prefix == "B" or current is None or current["entity_type"] != entity_type:
                if current is not None:
                    spans.append(current)
                current = {
                    "entity_type": entity_type,
                    "start": start,
                    "end": end,
                    "score": self.score,
                    "word": text[start:end],
                }
            else:
                current["end"] = end
                current["word"] = text[current["start"]:end]

        if current is not None:
            spans.append(current)
        return self._calibrate_spans(text, spans)

    def _accept_candidate(self, text: str, token: str, start: int, end: int, entity_type: str) -> bool:
        if entity_type != "PERSON":
            return True
        lowered = token.lower()
        blocked_terms = (
            "mã",
            "số",
            "đường",
            "phường",
            "xã",
            "huyện",
            "quận",
            "tỉnh",
            "tp",
            "thành phố",
            "ngân hàng",
            "bệnh viện",
            "rosuvastatin",
            "atorvastatin",
        )
        if any(char.isdigit() for char in token):
            return False
        if any(term in lowered for term in blocked_terms):
            return False
        if len(token.split()) < 2:
            return False
        if not self.person_context_required:
            return True

        context = text[max(0, start - 45):min(len(text), end + 45)].lower()
        cues = (
            "họ và tên",
            "họ tên",
            "tên bệnh nhân",
            "tên ứng viên",
            "tên nhân viên",
            "tên trưởng nhóm",
            "người phụ trách",
            "người nhận",
            "người gửi",
            "đại diện",
            "ông",
            "bà",
            "bác sĩ",
            "chủ thẻ",
            "ký và ghi rõ họ tên",
        )
        return any(cue in context for cue in cues)

    def _calibrate_spans(self, text: str, spans: List[dict]) -> List[dict]:
        calibrated = []
        for span in spans:
            score = self._calibrated_score(
                text=text,
                start=span["start"],
                end=span["end"],
                entity_type=span["entity_type"],
            )
            if score < self.min_score:
                continue
            span = dict(span)
            span["score"] = round(score, 3)
            calibrated.append(span)
        return calibrated

    def _calibrated_score(self, *, text: str, start: int, end: int, entity_type: str) -> float:
        if entity_type != "PERSON":
            return self.score

        value = text[start:end]
        lowered_value = value.lower()
        left = text[max(0, start - 60):start].lower()
        right = text[end:min(len(text), end + 60)].lower()
        context = f"{left} {right}"
        tokens = value.split()

        score = self.score
        strong_left_cues = (
            "họ và tên",
            "họ tên",
            "tên bệnh nhân",
            "tên ứng viên",
            "tên nhân viên",
            "tên trưởng nhóm",
            "người phụ trách",
            "người nhận",
            "người gửi",
            "người yêu cầu",
            "người lập báo cáo",
            "chủ thẻ",
            "đại diện",
            "bác sĩ",
            "cash receiver",
            "delivered by",
            "dr a/c name",
            "signature",
        )
        right_cues = (
            "mã nhân viên",
            "ngày sinh",
            "giới tính",
            "số cccd",
            "số cmnd",
            "số điện thoại",
            "email",
            "chức vụ",
            "chức danh",
        )
        if any(cue in left for cue in strong_left_cues):
            score += 0.25
        if any(cue in right for cue in right_cues):
            score += 0.12
        if 2 <= len(tokens) <= 4:
            score += 0.08
        if len(tokens) >= 5:
            score -= 0.08

        blocked_value_terms = (
            "mã",
            "số",
            "đường",
            "phường",
            "xã",
            "huyện",
            "quận",
            "tỉnh",
            "tp",
            "thành phố",
            "ngân hàng",
            "bệnh viện",
            "công an",
            "rosuvastatin",
            "atorvastatin",
            "vnd",
            "usd",
        )
        weak_context_terms = (
            "mã sân bay",
            "mã nhân viên",
            "mã khách hàng",
            "ngày cấp",
            "nơi cấp",
            "địa chỉ",
            "tọa độ",
            "số tiền",
            "tỷ giá",
            "thuốc",
            "chẩn đoán",
            "lĩnh vực công việc",
        )
        if any(char.isdigit() for char in value):
            score -= 0.4
        if any(term in lowered_value for term in blocked_value_terms):
            score -= 0.35
        if any(term in context for term in weak_context_terms):
            score -= 0.12
        if len(tokens) < 2:
            score -= 0.25

        return max(0.0, min(0.99, score))

    def _split_bio_tag(self, tag: str):
        if not tag or tag == "O":
            return "O", None
        if "-" not in tag:
            return "B", tag
        prefix, label = tag.split("-", 1)
        return prefix, label
