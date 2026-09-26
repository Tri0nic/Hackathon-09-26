"""Command line interface for sequential model training."""

from pathlib import Path
from typing import Annotated

import typer

from fire_risk.ml.training import TrainingConfig, train_all

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Train and inspect fire-risk model artifacts."""


@app.command()
def train(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
    task_type: Annotated[str, typer.Option()] = "GPU",
    seed: Annotated[int, typer.Option()] = 42,
    train_max_rows: Annotated[int, typer.Option()] = 1_000_000,
    calibration_max_rows: Annotated[int, typer.Option()] = 300_000,
    test_max_rows: Annotated[int | None, typer.Option()] = None,
    iterations: Annotated[int, typer.Option()] = 600,
    depth: Annotated[int, typer.Option()] = 8,
    learning_rate: Annotated[float, typer.Option()] = 0.08,
    early_stopping_rounds: Annotated[int, typer.Option()] = 75,
    progress_interval: Annotated[int, typer.Option()] = 25,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    """Train now/6h/12h/24h sequentially and write a versioned artifact."""
    manifest = train_all(
        TrainingConfig(
            input_path=input_path,
            output_dir=output,
            task_type=task_type,
            seed=seed,
            train_max_rows=train_max_rows,
            calibration_max_rows=calibration_max_rows,
            test_max_rows=test_max_rows,
            iterations=iterations,
            depth=depth,
            learning_rate=learning_rate,
            early_stopping_rounds=early_stopping_rounds,
            progress_interval=progress_interval,
            resume=resume,
        )
    )
    typer.echo(f"Training complete. Manifest: {manifest}")
    typer.echo(f"Metrics: {manifest.parent / 'metrics.json'}")


if __name__ == "__main__":
    app()
