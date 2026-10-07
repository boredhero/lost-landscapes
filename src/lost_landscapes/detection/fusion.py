"""Multi-pass result fusion using DBSCAN clustering and weighted scoring."""

import time
from collections import defaultdict

import numpy as np
from sklearn.cluster import DBSCAN

from lost_landscapes.detection.base import Candidate, FeatureType
from lost_landscapes.utils.log_manager import log


class ResultFuser:
    """Fuses detection candidates from multiple passes into unified detections."""

    def __init__(
        self,
        eps_m: float = 10.0,
        weights: dict[str, float] | None = None,
        multi_pass_bonus: float = 1.2,
        min_confidence: float = 0.3,
    ):
        self.eps_m = eps_m
        self.weights = weights or {}
        self.multi_pass_bonus = multi_pass_bonus
        self.min_confidence = min_confidence
        log.debug("result_fuser_init", eps_m=eps_m, multi_pass_bonus=multi_pass_bonus, min_confidence=min_confidence, weights=self.weights)

    def fuse(self, candidates: list[tuple[str, Candidate]]) -> list[Candidate]:
        """Cluster and merge candidates from multiple passes.

        Args:
            candidates: list of (pass_name, Candidate) tuples

        Returns:
            Merged candidates with fused confidence scores
        """
        if not candidates:
            log.debug("fusion_skip_empty", reason="no candidates to fuse")
            return []
        t0 = time.perf_counter()
        input_count = len(candidates)
        source_passes = sorted(set(pn for pn, _ in candidates))
        log.info("fusion_start", input_candidates=input_count, source_passes=source_passes, eps_m=self.eps_m, min_confidence=self.min_confidence)
        # Extract coordinates for clustering (approximate meters from degrees)
        coords = np.array(
            [[c.geometry.y, c.geometry.x] for _, c in candidates]
        )

        # Convert degrees to approximate meters for DBSCAN
        # 1 degree latitude ≈ 111,320m, 1 degree longitude varies by latitude
        mean_lat = np.mean(coords[:, 0])
        lat_scale = 111_320.0
        lon_scale = 111_320.0 * np.cos(np.radians(mean_lat))
        coords_m = coords * np.array([[lat_scale, lon_scale]])

        if len(candidates) == 1:
            _, cand = candidates[0]
            if cand.score >= self.min_confidence:
                log.info("fusion_single_candidate", score=round(cand.score, 3), accepted=True, elapsed_ms=round((time.perf_counter() - t0) * 1000, 2))
                return [cand]
            log.info("fusion_single_candidate", score=round(cand.score, 3), accepted=False, min_confidence=self.min_confidence, elapsed_ms=round((time.perf_counter() - t0) * 1000, 2))
            return []
        # Cluster with DBSCAN
        dbscan_t0 = time.perf_counter()
        clustering = DBSCAN(eps=self.eps_m, min_samples=1).fit(coords_m)
        labels = clustering.labels_
        dbscan_elapsed = time.perf_counter() - dbscan_t0
        num_clusters = len(set(labels) - {-1})
        num_noise = int(np.sum(labels == -1))
        log.info("dbscan_complete", eps_m=self.eps_m, input_points=len(candidates), num_clusters=num_clusters, noise_points=num_noise, elapsed_ms=round(dbscan_elapsed * 1000, 2))

        # Group candidates by cluster
        clusters: dict[int, list[tuple[str, Candidate]]] = defaultdict(list)
        for label, (pass_name, cand) in zip(labels, candidates):
            clusters[label].append((pass_name, cand))

        # Merge each cluster into a single detection
        merged: list[Candidate] = []
        for cluster_candidates in clusters.values():
            merged_candidate = self._merge_cluster(cluster_candidates)
            if merged_candidate.score >= self.min_confidence:
                merged.append(merged_candidate)

        elapsed = time.perf_counter() - t0
        confidence_scores = [c.score for c in merged]
        log.info("fusion_complete", input_candidates=input_count, output_candidates=len(merged), clusters=num_clusters, min_score=round(min(confidence_scores), 3) if confidence_scores else 0.0, max_score=round(max(confidence_scores), 3) if confidence_scores else 0.0, elapsed_ms=round(elapsed * 1000, 2))
        return sorted(merged, key=lambda c: c.score, reverse=True)

    def _merge_cluster(self, cluster: list[tuple[str, Candidate]]) -> Candidate:
        """Merge candidates in a spatial cluster into a single detection."""
        log.debug("merge_cluster_start", cluster_size=len(cluster), passes=[pn for pn, _ in cluster])
        pass_names = set()
        weighted_scores: list[float] = []
        total_weight = 0.0

        # Compute weighted average of centroid
        lats = []
        lons = []
        all_morphometrics: dict[str, list[float]] = defaultdict(list)
        feature_type_votes: dict[FeatureType, float] = defaultdict(float)
        outlines = []

        per_pass_data: list[dict] = []
        for pass_name, cand in cluster:
            pass_names.add(pass_name)
            weight = self.weights.get(pass_name, 1.0)
            weighted_scores.append(weight * cand.score)
            total_weight += weight
            lats.append(cand.geometry.y)
            lons.append(cand.geometry.x)
            for key, val in cand.morphometrics.items():
                all_morphometrics[key].append(val)
            feature_type_votes[cand.feature_type] += weight * cand.score
            if cand.outline is not None:
                outlines.append(cand.outline)
            per_pass_data.append({"pass_name": pass_name, "score": round(cand.score, 4), "feature_type": str(cand.feature_type), "morphometrics": {k: round(float(v), 4) if isinstance(v, (int, float)) else v for k, v in cand.morphometrics.items()}})

        # Weighted confidence
        confidence = sum(weighted_scores) / total_weight if total_weight > 0 else 0.0

        # Multi-pass agreement bonus
        if len(pass_names) >= 3:
            confidence *= self.multi_pass_bonus
        confidence = min(confidence, 1.0)

        # Majority vote for feature type
        feature_type = max(feature_type_votes, key=feature_type_votes.get)

        # Average morphometrics (skip non-numeric values)
        avg_morphometrics = {}
        for key, vals in all_morphometrics.items():
            numeric_vals = [v for v in vals if isinstance(v, (int, float))]
            if numeric_vals:
                avg_morphometrics[key] = float(np.mean(numeric_vals))
            else:
                avg_morphometrics[key] = vals[0]  # keep first non-numeric value

        # Use largest outline if available
        outline = None
        if outlines:
            outline = max(outlines, key=lambda o: o.area)

        from shapely.geometry import Point
        log.debug("merge_cluster_complete", num_passes=len(pass_names), passes=sorted(pass_names), confidence=round(confidence, 3), feature_type=str(feature_type), has_outline=outline is not None)
        return Candidate(
            geometry=Point(float(np.mean(lons)), float(np.mean(lats))),
            outline=outline,
            score=confidence,
            feature_type=feature_type,
            morphometrics=avg_morphometrics,
            metadata={
                "source_passes": sorted(pass_names),
                "num_passes": len(pass_names),
                "per_pass": per_pass_data,
            },
        )
