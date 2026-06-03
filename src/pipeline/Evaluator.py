from collections import defaultdict
from tqdm.auto import tqdm

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
    "DIA_CHI_EMAIL": "EMAIL_ADDRESS",
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
    "SO_CCCD_CMND": "ID",
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
        return_per_label: bool = False,
    ):
        """Evaluate Presidio analyzer predictions against ground truth privacy masks.
        
        Args:
            return_per_entity: If True, return grouped metrics by Presidio type (PERSON, LOCATION, etc.)
            return_per_label: If True, return fine-grained metrics by original dataset label
                              (HO_VA_TEN, DUONG_PHO, etc.). Tracks TP/FN per label to show
                              recall breakdown within each grouped category.
        
        Returns:
            - overall metrics dict (always)
            - per_entity_metrics dict (when return_per_entity=True)
            - per_label_metrics dict (when return_per_label=True)
            Returned as a tuple: (overall,), (overall, per_entity), (overall, per_label),
            or (overall, per_entity, per_label) depending on flags.
        """
        tp = fp = fn = 0
        mapped_types = set(self.label_to_presidio.values())
        per_entity = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        per_label = defaultdict(lambda: {"tp": 0, "fn": 0, "group": None})
        
        # Determine whether analyzer is an AnalyzerEngine or a BaseModel wrapper
        is_wrapper = hasattr(analyzer, "predict") and not hasattr(analyzer, "analyze")
        
        for _, row in tqdm(df_eval.iterrows(), total=len(df_eval), desc="Evaluating"):
            gt_spans_raw = [(item["start"], item["end"], item["label"]) for item in row["privacy_mask"]]
            
            if use_type_mapping:
                # Build mapped spans while preserving original labels for fine-grained tracking
                gt_mapped = []
                for start, end, label in gt_spans_raw:
                    mapped = self.label_to_presidio.get(label)
                    if mapped:
                        gt_mapped.append((start, end, mapped, label))
                
                gt_spans = [(s, e, m) for s, e, m, _ in gt_mapped]
                gt_original_labels = [orig for _, _, _, orig in gt_mapped]
            else:
                gt_spans = gt_spans_raw
                gt_original_labels = [label for _, _, label in gt_spans_raw]
            
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
            
            # Per-entity (grouped) tracking
            if use_type_mapping and return_per_entity:
                for pi, (_, _, pt) in enumerate(pred_spans):
                    if pi in matched_pred:
                        per_entity[pt]["tp"] += 1
                    else:
                        per_entity[pt]["fp"] += 1
                for gi, (_, _, gt) in enumerate(gt_spans):
                    if gi not in matched_gt:
                        per_entity[gt]["fn"] += 1
            
            # Per-label (fine-grained) tracking
            if use_type_mapping and return_per_label:
                for gi in range(len(gt_spans)):
                    orig_label = gt_original_labels[gi]
                    mapped_type = gt_spans[gi][2]
                    per_label[orig_label]["group"] = mapped_type
                    if gi in matched_gt:
                        per_label[orig_label]["tp"] += 1
                    else:
                        per_label[orig_label]["fn"] += 1
                        
        overall = self.metrics_from_counts(tp, fp, fn)
        
        # Build return value based on requested granularity
        results = [overall]
        
        if return_per_entity:
            per_entity_metrics = {
                entity: self.metrics_from_counts(counts["tp"], counts["fp"], counts["fn"])
                for entity, counts in per_entity.items()
            }
            results.append(per_entity_metrics)
        
        if return_per_label:
            per_label_metrics = {}
            for label, counts in per_label.items():
                label_tp = counts["tp"]
                label_fn = counts["fn"]
                recall = label_tp / (label_tp + label_fn) if (label_tp + label_fn) else 0.0
                per_label_metrics[label] = {
                    "group": counts["group"],
                    "tp": label_tp,
                    "fn": label_fn,
                    "recall": recall,
                }
            results.append(per_label_metrics)
        
        if len(results) == 1:
            return results[0]
        return tuple(results)
