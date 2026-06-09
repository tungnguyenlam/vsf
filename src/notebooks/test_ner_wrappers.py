"""Smoke test: verify NER wrapper architecture imports and basic functionality."""
import sys
import os

import pytest


pytestmark = pytest.mark.integration
if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run model-loading smoke tests.", allow_module_level=True)

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("=" * 60)
print("NER Wrapper Architecture — Smoke Test")
print("=" * 60)

# ----------------------------------------------------------------
# Test 1: All imports
# ----------------------------------------------------------------
print("\n[1/5] Testing imports...")
from src.pipeline.NERWrappers.BaseNERWrapper import BaseNERWrapper
from src.pipeline.NERWrappers.HFTransformersNER import HFTransformersNER
from src.pipeline.NERWrappers.SpacyNER import SpacyNER
from src.pipeline.NERWrappers.EnsembleNER import EnsembleNER
from src.pipeline.Recognizers.DeepLearningRecognizer import DeepLearningRecognizer
from src.pipeline.Recognizers.TransformersRecognizer import TransformersRecognizer
print("  All imports OK")

# ----------------------------------------------------------------
# Test 2: HFTransformersNER standalone
# ----------------------------------------------------------------
print("\n[2/5] Testing HFTransformersNER (standalone)...")
wrapper = HFTransformersNER(model_id="NlpHUST/ner-vietnamese-electra-base")
wrapper.load()
print(f"  Model loaded: {wrapper.is_loaded}")

sample = "Xin chào, tôi là Nguyễn Văn A, sống tại Hà Nội và làm việc tại Công ty ABC."
entities = wrapper.predict_entities(sample)
print(f"  Found {len(entities)} entities:")
for e in entities:
    print(f"    [{e['entity_type']}] ({e['score']:.2f}) -> \"{e['word']}\" [{e['start']}:{e['end']}]")

# ----------------------------------------------------------------
# Test 3: Backward-compatible TransformersRecognizer
# ----------------------------------------------------------------
print("\n[3/5] Testing TransformersRecognizer (backward-compat)...")
tr = TransformersRecognizer(model_id="NlpHUST/ner-vietnamese-electra-base", lang_code="vi")
tr.load_model()
print(f"  Presidio recognizer created: {tr._presidio_recognizer is not None}")
print(f"  Supported entities: {tr._presidio_recognizer.supported_entities}")

# ----------------------------------------------------------------
# Test 4: Full pipeline (spaCy + custom + transformers)
# ----------------------------------------------------------------
print("\n[4/5] Testing full pipeline integration...")
from src.pipeline.Recognizers.SpacyRecognizer import SpacyRecognizer
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer
from src.pipeline.BasePipeline import PIIPipeline

spacy_rec = SpacyRecognizer(model_name="xx_ent_wiki_sm", lang_code="vi")
custom_patterns = CustomPatternRecognizer()
dl_rec = DeepLearningRecognizer(ner_wrapper=wrapper, lang_code="vi")

pipeline = PIIPipeline(spacy_recognizer=spacy_rec, recognizers=[custom_patterns, dl_rec])
pipeline.load_model()

results = pipeline.predict(sample, language="vi")
print(f"  Full pipeline found {len(results)} results:")
for r in results:
    print(f"    [{r.entity_type}] ({r.score:.2f}) -> \"{sample[r.start:r.end]}\"")

# ----------------------------------------------------------------
# Test 5: Verify Step 2 != Step 3 (the original bug)
# ----------------------------------------------------------------
print("\n[5/5] Verifying transformers adds new detections...")
pipeline_no_dl = PIIPipeline(spacy_recognizer=SpacyRecognizer(model_name="xx_ent_wiki_sm", lang_code="vi"),
                              recognizers=[CustomPatternRecognizer()])
pipeline_no_dl.load_model()
results_no_dl = pipeline_no_dl.predict(sample, language="vi")

entities_without = {(r.entity_type, r.start, r.end) for r in results_no_dl}
entities_with = {(r.entity_type, r.start, r.end) for r in results}
new_detections = entities_with - entities_without

print(f"  Without DL model: {len(results_no_dl)} entities")
print(f"  With DL model:    {len(results)} entities")
print(f"  New detections from transformers: {len(new_detections)}")
if new_detections:
    for et, s, e in new_detections:
        print(f"    [{et}] -> \"{sample[s:e]}\"")
else:
    print("  WARNING: No new detections — investigate further!")

print("\n" + "=" * 60)
print("Smoke test complete.")
print("=" * 60)
