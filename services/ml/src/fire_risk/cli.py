"""Thin command-line adapter for the resumable full-data pipeline."""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from fire_risk.config import PipelineConfig
from fire_risk.data.pipeline import FullRunConfig, _normalize_events, run_full

__all__ = ["_normalize_events", "app"]

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Prepare immutable source journals into versioned model inputs."""


@app.command()
def prepare(
    events: Annotated[
        list[Path],
        typer.Option(exists=True, dir_okay=False, help="Repeat for each journal CSV."),
    ],
    channels: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    states: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option()],
    run_id: Annotated[str, typer.Option()],
    label_observed_until: Annotated[
        str, typer.Option(help="Confirmed label coverage end (ISO-8601 with timezone).")
    ],
    quality_thresholds: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="Frozen train-calibrated JSON; mutually exclusive with --calibrate.",
        ),
    ] = None,
    calibrate: Annotated[
        bool,
        typer.Option(
            help="Calibrate from 2019-2024 journals, then run with frozen thresholds."
        ),
    ] = False,
    config: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    source_timezone: Annotated[
        str, typer.Option(help="Timezone of naive source timestamps.")
    ] = "Europe/Moscow",
    device_seed: Annotated[int, typer.Option()] = 0,
    device_as_of: Annotated[str, typer.Option()] = "2026-09-24",
    temp_dir: Annotated[
        Path | None,
        typer.Option(
            help="Explicit spill/spool root. Required with --calibrate; use D: for production."
        ),
    ] = None,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
) -> None:
    """Write identity-checked stages; resume only verified complete artifacts."""
    if calibrate == (quality_thresholds is not None):
        raise typer.BadParameter(
            "Supply exactly one of --calibrate or --quality-thresholds"
        )
    if calibrate and temp_dir is None:
        raise typer.BadParameter("--calibrate requires an explicit --temp-dir")
    try:
        observed_until = datetime.fromisoformat(label_observed_until)
    except ValueError as exc:
        raise typer.BadParameter(
            "label-observed-until must be an ISO-8601 datetime"
        ) from exc
    try:
        result = run_full(
            FullRunConfig(
                events=tuple(events),
                channels=channels,
                states=states,
                output=output,
                run_id=run_id,
                temp_dir=temp_dir if temp_dir is not None else output / ".temp",
                observed_until=observed_until,
                quality_thresholds=quality_thresholds,
                settings=PipelineConfig.model_validate_json(
                    config.read_text(encoding="utf-8")
                )
                if config
                else PipelineConfig(),
                source_timezone=source_timezone,
                seed=device_seed,
                device_as_of=date.fromisoformat(device_as_of),
                resume=resume,
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"Prepared {result.directory}. Reused {len(result.reused_stages)} stages; built {len(result.built_stages)}."
    )


if __name__ == "__main__":
    app()
