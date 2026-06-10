from presidio_anonymizer import AnonymizerEngine

from src.pipeline.Pipelines import get_pipeline


SAMPLES = [
    (
        "Họ và tên: Nguyễn Văn An Ngày sinh: 12/05/1995 Số điện thoại "
        "0987654321 Email: an.nguyen@example.com CCCD: 012345678901 "
        "Số tài khoản: 123456789012."
    ),
    (
        "Họ và tên: Trần Thị Bình Mã nhân viên: NV20240601 Địa chỉ: Số 12 "
        "Đường Lê Lợi, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh."
    ),
    (
        "Tên công ty: Công ty TNHH Minh Long Mã số thuế: 0312345678 "
        "Mã giao dịch: GD20240615001."
    ),
]


def format_result(text, result):
    return {
        "entity_type": result.entity_type,
        "start": result.start,
        "end": result.end,
        "score": round(result.score, 4),
        "text": text[result.start : result.end],
    }


def dedupe_exact_spans(results):
    best_by_span = {}
    for result in results:
        key = (result.start, result.end)
        existing = best_by_span.get(key)
        if existing is None or result.score > existing.score:
            best_by_span[key] = result
    return sorted(best_by_span.values(), key=lambda item: (item.start, item.end))


def main():
    pipeline = get_pipeline("regex_recall", prediction_log_path=None)
    anonymizer = AnonymizerEngine()

    for index, text in enumerate(SAMPLES, start=1):
        results = dedupe_exact_spans(pipeline.predict(text))
        anonymized = anonymizer.anonymize(text=text, analyzer_results=results).text

        print(f"\nSample {index}")
        print("Input:")
        print(text)
        print("\nDetected spans:")
        for result in results:
            print(format_result(text, result))
        print("\nAnonymized:")
        print(anonymized)


if __name__ == "__main__":
    main()
