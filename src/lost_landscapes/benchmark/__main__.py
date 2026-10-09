"""Offline contract validation and point-baseline CLI. No services required."""

import json
from pathlib import Path

import click

from lost_landscapes.benchmark.evaluate import evaluate_points, manifest_digest
from lost_landscapes.benchmark.models import Manifest, PredictionSet


@click.group()
def main():
    """Validate evaluation data and run the bounded point baseline."""


def read_contract(path, model):
    try:
        return model.model_validate_json(path.read_text())
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("validate")
@click.argument("manifest_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def validate_manifest(manifest_path):
    """Validate geometry, evidence, provenance and spatial split isolation."""
    manifest = read_contract(manifest_path, Manifest)
    click.echo(
        json.dumps(
            {
                "valid": True,
                "dataset_id": manifest.dataset_id,
                "dataset_version": manifest.dataset_version,
                "purpose": manifest.purpose,
                "manifest_sha256": manifest_digest(manifest),
                "regions": len(manifest.regions),
                "labels": len(manifest.labels),
            },
            indent=2,
        )
    )


@main.command("schema")
@click.argument("contract", type=click.Choice(["manifest", "predictions"]))
def schema(contract):
    """Print the version 1 JSON Schema (spatial checks also require validate)."""
    model = Manifest if contract == "manifest" else PredictionSet
    click.echo(json.dumps(model.model_json_schema(), indent=2))


@main.command("score-points")
@click.argument("manifest_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("predictions_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def score_points(manifest_path, predictions_path):
    """Score against reviewed point labels; emit a reproducible JSON report."""
    manifest = read_contract(manifest_path, Manifest)
    predictions = read_contract(predictions_path, PredictionSet)
    try:
        result = evaluate_points(manifest, predictions)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
