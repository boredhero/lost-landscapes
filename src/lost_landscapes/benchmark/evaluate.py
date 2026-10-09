"""A bounded, same-family point baseline; not a line/footprint evaluator."""

import hashlib
import json

import numpy as np
from pyproj import Transformer
from scipy.optimize import linear_sum_assignment
from shapely.ops import unary_union

from lost_landscapes.benchmark.models import Manifest, PredictionSet, project

MAX_MATCH_PAIRS = 1_000_000


def manifest_digest(manifest: Manifest) -> str:
    """Stable across JSON whitespace/key order; revisions change the digest."""
    payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def match_points(predictions, labels, tolerance):
    """Maximum-cardinality one-to-one matching, then minimum total distance."""
    if not predictions or not labels:
        return [], np.empty((len(predictions), len(labels)))
    if len(predictions) * len(labels) > MAX_MATCH_PAIRS:
        raise ValueError("Point matching exceeds the baseline's one-million-pair limit")
    distances = np.array([[p.distance(label) for label in labels] for p in predictions])
    # One invalid edge costs more than every possible valid edge together.
    penalty = (min(distances.shape) + 1) * (tolerance + 1)
    rows, cols = linear_sum_assignment(np.where(distances <= tolerance, distances, penalty))
    return [
        (int(r), int(c)) for r, c in zip(rows, cols, strict=True) if distances[r, c] <= tolerance
    ], distances


def evaluate_points(manifest: Manifest, prediction_set: PredictionSet) -> dict:
    if (
        prediction_set.dataset_id != manifest.dataset_id
        or prediction_set.dataset_version != manifest.dataset_version
        or prediction_set.manifest_sha256 != manifest_digest(manifest)
    ):
        raise ValueError("Predictions must reference the exact dataset version and manifest digest")
    transformer = Transformer.from_crs(
        "EPSG:4326", manifest.protocol.evaluation_crs, always_xy=True
    )
    tolerance = manifest.protocol.point_tolerance_m
    regions = [r for r in manifest.regions if r.split == prediction_set.split]
    if not regions:
        raise ValueError("Selected split has no regions")
    region_shapes = {r.id: project(r.geometry, transformer) for r in regions}
    located = {r.id: [] for r in regions}
    for prediction in sorted(prediction_set.predictions, key=lambda p: p.id):
        geom = project(prediction.geometry, transformer)
        region_id = next((key for key, area in region_shapes.items() if area.covers(geom)), None)
        if region_id is None:
            raise ValueError(f"Prediction {prediction.id} lies outside the selected split")
        located[region_id].append((prediction, geom))

    families = {}
    for family in sorted(prediction_set.families):
        matches, false_positives, misses, duplicates, excluded, excluded_labels = (
            [],
            [],
            [],
            [],
            [],
            [],
        )
        area_m2 = 0.0
        for region in regions:
            labels = sorted(
                [
                    label
                    for label in manifest.labels
                    if label.region_id == region.id and label.family == family
                ],
                key=lambda label: label.id,
            )
            predictions = [(p, g) for p, g in located[region.id] if p.family == family]
            if not any(
                r.family == family and r.completeness == "exhaustive" for r in region.reviews
            ):
                excluded.extend(
                    {"id": p.id, "reason": "region_not_exhaustively_reviewed"}
                    for p, _ in predictions
                )
                excluded_labels.extend(
                    label.id for label in labels if label.reviews[-1].status == "present"
                )
                continue
            uncertain = unary_union(
                [
                    project(label.geometry, transformer).buffer(tolerance)
                    for label in labels
                    if label.reviews[-1].status == "uncertain"
                ]
            )
            area_m2 += region_shapes[region.id].difference(uncertain).area
            truth, truth_shapes = [], []
            for label in labels:
                if label.reviews[-1].status != "present":
                    continue
                if label.geometry.type != "Point":
                    raise ValueError(
                        f"Label {label.id} requires line/footprint evaluation; point scoring is unavailable"
                    )
                geom = project(label.geometry, transformer)
                if uncertain.covers(geom):
                    excluded_labels.append(label.id)
                else:
                    truth.append(label)
                    truth_shapes.append(geom)
            retained = []
            for prediction, geom in predictions:
                if uncertain.covers(geom):
                    excluded.append(
                        {"id": prediction.id, "reason": "unresolved_label_neighborhood"}
                    )
                else:
                    retained.append((prediction, geom))
            pairs, distances = match_points([g for _, g in retained], truth_shapes, tolerance)
            matched_predictions = {p for p, _ in pairs}
            matched_truth = {t for _, t in pairs}
            matches.extend(
                {
                    "prediction_id": retained[p][0].id,
                    "label_id": truth[t].id,
                    "distance_m": float(distances[p, t]),
                }
                for p, t in pairs
            )
            misses.extend(label.id for t, label in enumerate(truth) if t not in matched_truth)
            for p, (prediction, _) in enumerate(retained):
                if p not in matched_predictions:
                    false_positives.append(prediction.id)
                    if truth and np.any(distances[p] <= tolerance):
                        duplicates.append(prediction.id)
        tp, fp, fn = len(matches), len(false_positives), len(misses)
        families[family] = {
            "status": "scored" if area_m2 else "no_reviewed_area",
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "reviewed_area_km2": area_m2 / 1_000_000,
            "false_positives_per_km2": fp / (area_m2 / 1_000_000) if area_m2 else None,
            "matches": matches,
            "missed_label_ids": misses,
            "false_positive_ids": false_positives,
            "duplicate_prediction_ids": duplicates,
            "excluded_predictions": excluded,
            "excluded_label_ids": excluded_labels,
        }
    return {
        "report_version": 1,
        "evaluator": "same-family-points-v1",
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.dataset_version,
        "manifest_sha256": manifest_digest(manifest),
        "purpose": manifest.purpose,
        "predictions_sha256": hashlib.sha256(
            json.dumps(
                prediction_set.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "split": prediction_set.split,
        "protocol": manifest.protocol.model_dump(mode="json"),
        "algorithm": prediction_set.algorithm,
        "algorithm_version": prediction_set.algorithm_version,
        "configuration": prediction_set.configuration,
        "families": families,
        "limitations": "Point baseline only. Excluded areas are not negative examples. Synthetic fixtures do not measure real-world accuracy.",
    }
