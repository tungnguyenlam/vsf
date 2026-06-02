from collections import defaultdict

DEFAULT_LABEL_TO_PRESIDIO = {
    "HO_VA_TEN": "PERSON",
    "HO": "PERSON",
    "TEN": "PERSON",
    "TEN_DEM": "PERSON",
    "NGAY": "DATE_TIME",
    "NGAY_SINH": "DATE_TIME",
    "THANG": "DATE_TIME",
    "NAM": "DATE_TIME",
    "SO_DIEN_THOAI": "PHONE_NUMBER",
    "EMAIL": "EMAIL_ADDRESS",
    "THANH_PHO_TINH": "LOCATION",
    "QUAN_HUYEN": "LOCATION",
    "PHUONG_XA": "LOCATION",
    "DUONG_PHO": "LOCATION",
    "SO_NHA_TOA_NHA": "LOCATION",
    "QUOC_GIA": "LOCATION",
    "SO_TAI_KHOAN": "BANK_ACCOUNT",
    "TEN_TO_CHUC": "ORGANIZATION",
    "TEN_NGAN_HANG": "ORGANIZATION",
    "MA_NHAN_VIEN": "ID",
    "MA_GIAO_DICH": "ID",
    "MA_SO_THUE": "ID",
    "SO_CMND": "ID",
    "SO_CCCD": "ID",
    "SO_HO_CHIEU": "ID",
}

class PIIEvaluator:
    """Modular evaluator measuring precision, recall, and F1 counts for PII detection."""
    
    def __init__(self, label_to_presidio: dict = None):
        self.label_to_presidio = label_to_presidio or DEFAULT_LABEL_TO_PRESIDIO
        
    def spans_overlap(self, a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """Check if two character spans overlap."""
        return max(a_start, b_start) < min(a_end, b_end)
        
    def metrics_from_counts(self, tp: int, fp: int, fn: int) -> dict:
        """Calculate precision, recall, and F1 score from count metrics."""
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}
        
    def evaluate_presidio(
        self,
        df_eval,
        analyzer,
        language: str = "xx",
        score_threshold: float = 0.0,
        use_type_mapping: bool = False,
        return_per_entity: bool = False,
    ):
        """Evaluate Presidio analyzer predictions against ground truth privacy masks."""
        tp = fp = fn = 0
        mapped_types = set(self.label_to_presidio.values())
        per_entity = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        
        # Determine whether analyzer is an AnalyzerEngine or a BaseModel wrapper
        is_wrapper = hasattr(analyzer, "predict") and not hasattr(analyzer, "analyze")
        
        for _, row in df_eval.iterrows():
            gt_spans = [(item["start"], item["end"], item["label"]) for item in row["privacy_mask"]]
            if use_type_mapping:
                gt_spans = [
                    (start, end, self.label_to_presidio.get(label))
                    for start, end, label in gt_spans
                    if self.label_to_presidio.get(label)
                ]
            
            if is_wrapper:
                preds = analyzer.predict(inputs=row["source_text"], language=language, score_threshold=score_threshold)
            else:
                preds = analyzer.analyze(text=row["source_text"], language=language, score_threshold=score_threshold)
                
            pred_spans = [(p.start, p.end, p.entity_type) for p in preds]
            if use_type_mapping:
                pred_spans = [p for p in pred_spans if p[2] in mapped_types]
                
            matched_gt = set()
            matched_pred = set()
            for pi, (ps, pe, pt) in enumerate(pred_spans):
                for gi, (gs, ge, gt) in enumerate(gt_spans):
                    if gi in matched_gt:
                        continue
                    if use_type_mapping and pt != gt:
                        continue
                    if self.spans_overlap(ps, pe, gs, ge):
                        matched_gt.add(gi)
                        matched_pred.add(pi)
                        break
            tp += len(matched_pred)
            fp += len(pred_spans) - len(matched_pred)
            fn += len(gt_spans) - len(matched_gt)
            
            if use_type_mapping and return_per_entity:
                for pi, (_, _, pt) in enumerate(pred_spans):
                    if pi in matched_pred:
                        per_entity[pt]["tp"] += 1
                    else:
                        per_entity[pt]["fp"] += 1
                for gi, (_, _, gt) in enumerate(gt_spans):
                    if gi not in matched_gt:
                        per_entity[gt]["fn"] += 1
                        
        overall = self.metrics_from_counts(tp, fp, fn)
        if not return_per_entity:
            return overall
            
        per_entity_metrics = {
            entity: self.metrics_from_counts(counts["tp"], counts["fp"], counts["fn"])
            for entity, counts in per_entity.items()
        }
        return overall, per_entity_metrics
