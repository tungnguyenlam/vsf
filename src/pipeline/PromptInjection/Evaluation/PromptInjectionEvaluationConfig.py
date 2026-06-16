from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptInjectionEvaluationConfig:
    dataset: str = "local_vietnamese_seed"
    detector: str = "rule_based_prompt_injection"
    split: str = "test"
    limit: int | None = None
    random_state: int = 42
    log_path: Path | None = None
    no_log: bool = False
    include_source_text: bool = False
    run_id: str | None = None
    train_strategy: str = "none"

    @classmethod
    def from_args(cls, args):
        return cls(
            dataset=args.dataset,
            detector=args.detector,
            split=args.split,
            limit=args.limit,
            random_state=args.random_state,
            log_path=Path(args.log_path) if args.log_path is not None else None,
            no_log=args.no_log,
            include_source_text=args.include_source_text,
            run_id=args.run_id,
            train_strategy=args.train_strategy,
        )
