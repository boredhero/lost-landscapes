"""Evaluation contracts fail closed; counting tests use invented geometry only."""

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError
from shapely.geometry import Point

from lost_landscapes.benchmark.__main__ import main
from lost_landscapes.benchmark.evaluate import evaluate_points, manifest_digest, match_points
from lost_landscapes.benchmark.models import Manifest, PredictionSet

FIXTURES = Path(__file__).parents[1] / "fixtures" / "benchmark"


@pytest.fixture
def raw():
    return json.loads((FIXTURES / "synthetic-manifest.json").read_text())


@pytest.fixture
def predictions():
    return json.loads((FIXTURES / "synthetic-predictions.json").read_text())


def score(raw, predictions):
    manifest = Manifest.model_validate(raw)
    predictions["manifest_sha256"] = manifest_digest(manifest)
    return evaluate_points(manifest, PredictionSet.model_validate(predictions))


def test_fixture_validates_and_schema_describes_geometry_union(raw):
    manifest = Manifest.model_validate(raw)
    assert manifest.purpose == "synthetic"
    assert {r.split for r in manifest.regions} == {"train", "validation", "test"}
    assert (
        Manifest.model_json_schema()["$defs"]["Label"]["properties"]["geometry"]["discriminator"][
            "propertyName"
        ]
        == "type"
    )


@pytest.mark.parametrize("crs", ["EPSG:4326", "EPSG:3857", "EPSG:3395", "EPSG:2263", "not-a-crs"])
def test_rejects_unsuitable_distance_crs(raw, crs):
    raw["protocol"]["evaluation_crs"] = crs
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)


def test_region_must_be_in_crs_area(raw):
    raw["protocol"]["evaluation_crs"] = "EPSG:32630"
    with pytest.raises(ValidationError, match="area of use"):
        Manifest.model_validate(raw)


@pytest.mark.parametrize(
    "change,match",
    [
        ("duplicate_feature", "physical feature"),
        ("unknown_survey", "Unknown survey"),
        ("outside_region", "outside its region"),
        ("same_group", "independence group"),
        ("overlap", "overlap"),
        ("missing_evidence", "at least 1 item"),
        ("bad_history", "consecutive"),
        ("unknown_field", "Extra inputs"),
        ("open_ring", "explicitly closed"),
    ],
)
def test_rejects_invalid_evidence_or_spatial_contract(raw, change, match):
    if change == "duplicate_feature":
        raw["labels"][1]["feature_id"] = raw["labels"][0]["feature_id"]
    elif change == "unknown_survey":
        raw["regions"][0]["survey_ids"] = ["missing"]
    elif change == "outside_region":
        raw["labels"][0]["geometry"]["coordinates"] = [-80, 40.5]
    elif change == "same_group":
        raw["regions"][1]["independence_group"] = "train"
    elif change == "overlap":
        raw["regions"][1]["geometry"] = raw["regions"][0]["geometry"]
    elif change == "missing_evidence":
        raw["labels"][0]["reviews"][0]["evidence"] = []
    elif change == "bad_history":
        raw["labels"][0]["reviews"][0]["revision"] = 2
    elif change == "unknown_field":
        raw["regions"][0]["reviewed"] = True
    elif change == "open_ring":
        raw["regions"][0]["geometry"]["coordinates"][0].pop()
    with pytest.raises(ValidationError, match=match):
        Manifest.model_validate(raw)


def test_nearby_nonoverlapping_regions_in_different_splits_rejected(raw):
    # Move validation just east of training, leaving only an ~8 m gap.
    raw["labels"] = []
    raw["regions"][1]["geometry"] = copy.deepcopy(raw["regions"][0]["geometry"])
    for position in raw["regions"][1]["geometry"]["coordinates"][0]:
        position[0] += 0.0021
    with pytest.raises(ValidationError, match="spatial buffer"):
        Manifest.model_validate(raw)


def test_two_ids_cannot_double_count_same_family_same_geometry(raw):
    duplicate = copy.deepcopy(raw["labels"][2])
    duplicate.update(id="duplicate-id", feature_id="another-physical-id")
    raw["labels"].append(duplicate)
    with pytest.raises(ValidationError, match="Coincident"):
        Manifest.model_validate(raw)


def test_latest_review_controls_status_without_erasing_history(raw, predictions):
    label = raw["labels"][2]
    review = copy.deepcopy(label["reviews"][0])
    review.update(
        revision=2, status="uncertain", observation="A second reviewer cannot resolve the example."
    )
    label["reviews"].append(review)
    result = score(raw, predictions)["families"]["raised"]
    assert result["true_positives"] == 0
    assert len(result["excluded_predictions"]) == 3
    assert Manifest.model_validate(raw).labels[2].reviews[0].status == "present"


def test_empty_predictions_are_misses_not_skips(raw, predictions):
    predictions["predictions"] = []
    result = score(raw, predictions)
    assert result["families"]["raised"]["false_negatives"] == 2
    assert result["families"]["depression"]["false_negatives"] == 1
    assert result["families"]["raised"]["recall"] == 0
    assert result["families"]["raised"]["precision"] is None


def test_one_to_one_family_matching_counts_duplicates_and_wrong_family(raw, predictions):
    result = score(raw, predictions)
    raised = result["families"]["raised"]
    assert (raised["true_positives"], raised["false_positives"], raised["false_negatives"]) == (
        1,
        2,
        1,
    )
    assert raised["duplicate_prediction_ids"] == ["duplicate"]
    assert "wrong-family" in raised["false_positive_ids"]
    assert raised["excluded_predictions"] == [
        {"id": "unresolved", "reason": "unresolved_label_neighborhood"}
    ]
    assert result["families"]["depression"]["missed_label_ids"] == ["test-depression"]
    assert raised["false_positives_per_km2"] == pytest.approx(2 / raised["reviewed_area_km2"])


def test_unreviewed_area_is_not_a_negative_example(raw, predictions):
    raw["regions"][2]["reviews"] = []
    result = score(raw, predictions)["families"]["raised"]
    assert result["true_positives"] == result["false_positives"] == result["false_negatives"] == 0
    assert result["precision"] is None and result["recall"] is None
    assert result["reviewed_area_km2"] == 0
    assert len(result["excluded_predictions"]) == 4
    assert len(result["excluded_label_ids"]) == 2


def test_reviewed_negative_only_area_counts_false_positive(raw, predictions):
    raw["labels"] = [label for label in raw["labels"] if label["region_id"] != "test"]
    predictions["predictions"] = predictions["predictions"][:1]
    result = score(raw, predictions)["families"]["raised"]
    assert result["false_positives"] == 1
    assert result["recall"] is None


def test_maximum_cardinality_beats_greedy_nearest():
    # Greedy gives the first prediction A, stranding the second; global matching gets both.
    pairs, _ = match_points([Point(4, 0), Point(0, 0)], [Point(0, 0), Point(9, 0)], 6)
    assert pairs == [(0, 1), (1, 0)]


def test_distance_limit_prevents_nearby_wrong_object_from_counting():
    pairs, _ = match_points([Point(11, 0)], [Point(0, 0)], 10)
    assert pairs == []


def test_geometry_or_split_changes_invalidate_prediction_manifest(raw, predictions):
    manifest = Manifest.model_validate(raw)
    assert predictions["manifest_sha256"] == manifest_digest(manifest)
    raw["labels"][2]["geometry"]["coordinates"][0] += 0.00001
    with pytest.raises(ValueError, match="exact dataset"):
        evaluate_points(Manifest.model_validate(raw), PredictionSet.model_validate(predictions))


def test_nonpoint_truth_is_not_silently_reduced_to_centroid(raw, predictions):
    raw["labels"][2]["geometry"] = {
        "type": "LineString",
        "coordinates": [[-80.0036, 40.4915], [-80.0035, 40.4915]],
    }
    with pytest.raises(ValueError, match="line/footprint"):
        score(raw, predictions)


def test_predictions_cannot_leak_from_other_split(raw, predictions):
    predictions["predictions"][0]["geometry"]["coordinates"] = [-80.019, 40.491]
    with pytest.raises(ValueError, match="outside the selected split"):
        score(raw, predictions)


def test_cli_outputs_valid_json_and_fails_on_bad_manifest(raw, tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(FIXTURES / "synthetic-manifest.json")])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["purpose"] == "synthetic"
    result = runner.invoke(
        main,
        [
            "score-points",
            str(FIXTURES / "synthetic-manifest.json"),
            str(FIXTURES / "synthetic-predictions.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["families"]["raised"]["false_negatives"] == 1
    raw["schema_version"] = 99
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))
    result = runner.invoke(main, ["validate", str(path)])
    assert result.exit_code != 0
    assert "Error:" in result.output


def test_json_formatting_does_not_change_digest(raw):
    first = Manifest.model_validate(raw)
    second = Manifest.model_validate_json(json.dumps(raw, sort_keys=True, indent=4))
    assert manifest_digest(first) == manifest_digest(second)
