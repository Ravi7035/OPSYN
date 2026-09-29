"""CLI entrypoint for the OPSYN evaluation harness.

Run from the ``backend`` directory::

    python -m app.evaluation.run --mode cold --reasoning-model deterministic
    python -m app.evaluation.run --mode experienced --reasoning-model llm
    python -m app.evaluation.run --mode all --reasoning-model llm
    python -m app.evaluation.run --mode all --reasoning-model both
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.evaluation.runner import (
    REASONING_CHOICES,
    compare_reports,
    render_text_report,
    run_cold_evaluation,
    run_experienced_evaluation,
    run_learning_experiment,
    run_misleading_memory_experiment,
    save_report,
    seed_incidents_from_report,
)
from app.evaluation.scenarios import SCENARIOS
from app.services.payment_simulator import PaymentSimulator


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OPSYN evaluation (deterministic or LLM)")
    parser.add_argument(
        "--mode",
        choices=["cold", "experienced", "both", "experiments", "all"],
        default="both",
        help="Which evaluation to run",
    )
    parser.add_argument(
        "--reasoning-model",
        choices=[*REASONING_CHOICES, "both"],
        default="deterministic",
        help="Reasoning backend: deterministic, llm (Groq), or both (independent runs)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help=f"Subset of scenarios (default: all {len(SCENARIOS)})",
    )
    parser.add_argument(
        "--out",
        default="evaluation",
        help="Output directory for JSON reports",
    )
    return parser.parse_args(argv)


def _prefix(reasoning: str, name: str, single: bool) -> str:
    """File name, prefixed per reasoning backend unless only one runs."""
    return name if single else f"{reasoning}_{name}"


async def _run_reasoning(
    mode: str,
    reasoning: str,
    scenarios: list[str] | None,
    out: Path,
    single: bool,
) -> int:
    simulator = PaymentSimulator()
    cold = None

    if mode in ("cold", "both", "all"):
        cold = await run_cold_evaluation(scenarios, simulator, reasoning)
        save_report(cold, out / _prefix(reasoning, "cold_results.json", single))
        print(f"[{reasoning}] cold: "
              f"{cold.totals.get('resolved_scenarios', 0):.0f} / "
              f"{cold.totals.get('total_scenarios', 0):.0f} resolved")

    if mode in ("experienced", "both", "all"):
        if cold is None:
            # Independent baseline first: experienced seeds must be genuine
            # prior experiences, so run cold silently when not requested.
            cold = await run_cold_evaluation(scenarios, simulator, reasoning)
        seeds = seed_incidents_from_report(cold)
        experienced = await run_experienced_evaluation(
            seeds, scenarios, simulator, reasoning
        )
        save_report(
            experienced, out / _prefix(reasoning, "experienced_results.json", single)
        )
        print(f"[{reasoning}] experienced: "
              f"{experienced.totals.get('resolved_scenarios', 0):.0f} / "
              f"{experienced.totals.get('total_scenarios', 0):.0f} resolved")
        if mode in ("both", "all"):
            save_report(cold, out / _prefix(reasoning, "cold_results.json", single))
            comparison = compare_reports(cold, experienced)
            save_report(
                comparison, out / _prefix(reasoning, "comparison.json", single)
            )
            print("")
            print(render_text_report(cold, experienced, comparison))

    if mode in ("experiments", "all"):
        learning = await run_learning_experiment(simulator, reasoning)
        save_report(
            learning, out / _prefix(reasoning, "learning_experiment.json", single)
        )
        print(f"[{reasoning}] learning experiment: "
              f"stage1 resolved={learning.stage1.resolved}, "
              f"stage2 resolved={learning.stage2.resolved}, "
              f"stage2 recalled={learning.stage2_recalled_memory_ids}")
        misleading = await run_misleading_memory_experiment(simulator, reasoning)
        save_report(
            misleading,
            out / _prefix(reasoning, "misleading_memory_experiment.json", single),
        )
        print(f"[{reasoning}] misleading memory: "
              f"db_hypothesis={misleading.db_hypothesis_status}, "
              f"final_action={misleading.final_action}, "
              f"resolved={misleading.resolved}")

    return 0


async def _run(
    mode: str,
    reasoning: str,
    scenarios: list[str] | None,
    out: Path,
) -> int:
    backends = list(REASONING_CHOICES) if reasoning == "both" else [reasoning]
    single = len(backends) == 1
    for backend in backends:
        if not single:
            print(f"=== reasoning backend: {backend} ===")
        code = await _run_reasoning(mode, backend, scenarios, out, single)
        if code != 0:
            return code
    print(f"reports written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    scenarios = args.scenarios or None
    if scenarios:
        unknown = [s for s in scenarios if s not in SCENARIOS]
        if unknown:
            print(f"unknown scenarios: {unknown}", file=sys.stderr)
            return 2
    return asyncio.run(
        _run(args.mode, args.reasoning_model, scenarios, Path(args.out))
    )


if __name__ == "__main__":
    raise SystemExit(main())
