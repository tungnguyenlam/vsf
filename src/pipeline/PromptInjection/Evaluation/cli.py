import argparse
import json

from src.pipeline.PromptInjection.Datasets import list_prompt_injection_dataset_names
from src.pipeline.PromptInjection.Evaluation.PromptInjectionEvaluationConfig import (
    PromptInjectionEvaluationConfig,
)
from src.pipeline.PromptInjection.Evaluation.PromptInjectionEvaluationRunner import (
    PromptInjectionEvaluationRunner,
)


def create_arg_parser():
    parser = argparse.ArgumentParser(
        description="Evaluate the Vietnamese-first prompt-injection detector."
    )
    parser.add_argument(
        "--dataset",
        default="local_vietnamese_seed",
        choices=list_prompt_injection_dataset_names(),
    )
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--log-path", default=None)
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--include-source-text", action="store_true")
    parser.add_argument("--run-id", default=None)
    return parser


def evaluate_from_args(args):
    return PromptInjectionEvaluationRunner(
        PromptInjectionEvaluationConfig.from_args(args)
    ).run()


def main(argv=None):
    args = create_arg_parser().parse_args(argv)
    output = evaluate_from_args(args)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output
