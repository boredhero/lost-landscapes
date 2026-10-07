"""Training data pipeline for ML models.

Extracts training samples from processed DEMs using ground truth data:
- Positive samples: patches centered on known karst/mine features
- Negative samples: random patches from non-feature terrain

Supports training for:
- Random Forest (feature vectors from morphometric extraction)
- U-Net (multi-channel image patches)
- YOLO (hillshade tiles with bounding box annotations)
"""

import time
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from lost_landscapes.detection.passes.random_forest import FEATURE_NAMES, extract_features
from lost_landscapes.utils.log_manager import log


def extract_rf_training_data(
    dem: NDArray[np.float32],
    resolution: float,
    positive_masks: list[NDArray[np.bool_]],
    derivatives: dict[str, NDArray[np.float32]],
    n_negatives: int = 0,
    rng: np.random.Generator | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.int32]]:
    """Extract Random Forest training features from a DEM.

    Args:
        dem: DEM array
        resolution: cell size in meters
        positive_masks: list of boolean masks for known features
        derivatives: pre-computed derivative arrays (slope, tpi, svf, fill_difference)
        n_negatives: number of random negative patches to generate
        rng: random number generator

    Returns:
        (features_array, labels) where labels are 1=feature, 0=non-feature
    """
    t0 = time.perf_counter()
    log.info("rf_training_data_extraction_start", dem_shape=list(dem.shape), resolution=resolution, positive_masks=len(positive_masks), n_negatives=n_negatives)
    if rng is None:
        rng = np.random.default_rng(42)
    slope = derivatives["slope"]
    tpi = derivatives["tpi"]
    svf = derivatives["svf"]
    features_list = []
    labels_list = []
    skipped_small = 0
    # Positive samples from known features
    for mask in positive_masks:
        if np.sum(mask) < 4:
            skipped_small += 1
            continue
        feats = extract_features(dem, mask, slope, tpi, svf, resolution)
        features_list.append(feats)
        labels_list.append(1)
    if skipped_small:
        log.debug("rf_positive_masks_skipped", skipped=skipped_small, reason="mask_too_small")
    # Negative samples from random locations
    h, w = dem.shape
    fill_diff = derivatives.get("fill_difference", np.zeros_like(dem))
    neg_skipped_depression = 0
    for _ in range(n_negatives):
        # Random patch that is NOT a depression
        cy = rng.integers(20, h - 20)
        cx = rng.integers(20, w - 20)
        radius = rng.integers(5, 15)
        mask = np.zeros((h, w), dtype=bool)
        y, x = np.mgrid[0:h, 0:w]
        mask[(y - cy) ** 2 + (x - cx) ** 2 < radius ** 2] = True
        # Skip if this happens to be a real depression
        if np.max(fill_diff[mask]) > 0.5:
            neg_skipped_depression += 1
            continue
        feats = extract_features(dem, mask, slope, tpi, svf, resolution)
        features_list.append(feats)
        labels_list.append(0)
    if neg_skipped_depression:
        log.debug("rf_negative_patches_skipped", skipped=neg_skipped_depression, reason="overlaps_depression")
    if not features_list:
        log.warning("rf_training_data_empty", positive_masks=len(positive_masks), n_negatives=n_negatives)
        return np.empty((0, len(FEATURE_NAMES))), np.empty(0, dtype=np.int32)
    elapsed = round(time.perf_counter() - t0, 2)
    n_pos = sum(1 for l in labels_list if l == 1)
    n_neg = sum(1 for l in labels_list if l == 0)
    log.info("rf_training_data_extraction_complete", total_samples=len(features_list), positives=n_pos, negatives=n_neg, elapsed_s=elapsed)
    return np.array(features_list), np.array(labels_list, dtype=np.int32)


def train_random_forest(
    X: NDArray[np.float64],
    y: NDArray[np.int32],
    output_path: Path,
    n_estimators: int = 200,
    class_weight: str = "balanced",
) -> dict:
    """Train a Random Forest classifier and save to disk.

    Returns dict with training metrics.
    """
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    t0 = time.perf_counter()
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    log.info("rf_training_start", n_samples=len(X), n_positive=n_pos, n_negative=n_neg, n_estimators=n_estimators, class_weight=class_weight, output_path=str(output_path))
    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        class_weight=class_weight,
        max_depth=20,
        min_samples_split=5,
        random_state=42,
        n_jobs=-1,
    )
    # Cross-validation
    if len(X) >= 10:
        t_cv = time.perf_counter()
        cv_folds = min(5, len(X))
        cv_scores = cross_val_score(clf, X, y, cv=cv_folds, scoring="roc_auc")
        auc_mean = float(np.mean(cv_scores))
        auc_std = float(np.std(cv_scores))
        log.info("rf_cross_validation_complete", folds=cv_folds, auc_mean=round(auc_mean, 4), auc_std=round(auc_std, 4), elapsed_s=round(time.perf_counter() - t_cv, 2))
    else:
        auc_mean, auc_std = 0.0, 0.0
        log.warning("rf_cross_validation_skipped", n_samples=len(X), reason="too_few_samples")
    # Train on full data
    t_fit = time.perf_counter()
    clf.fit(X, y)
    log.info("rf_fit_complete", elapsed_s=round(time.perf_counter() - t_fit, 2))
    # Feature importance
    importances = dict(zip(FEATURE_NAMES, clf.feature_importances_.tolist()))
    top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]
    log.info("rf_feature_importances", top_5={k: round(v, 4) for k, v in top_features})
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, output_path)
    elapsed = round(time.perf_counter() - t0, 2)
    log.info("rf_training_complete", model_path=str(output_path), auc_mean=round(auc_mean, 4), elapsed_s=elapsed)
    return {
        "n_samples": len(X),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "cv_auc_mean": auc_mean,
        "cv_auc_std": auc_std,
        "feature_importances": importances,
        "model_path": str(output_path),
    }


def extract_unet_patches(
    dem: NDArray[np.float32],
    derivatives: dict[str, NDArray[np.float32]],
    positive_centers: list[tuple[int, int]],
    patch_size: int = 256,
    n_negatives: int = 0,
    rng: np.random.Generator | None = None,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Extract U-Net training patches (5-channel input + binary mask).

    Args:
        derivatives: pre-computed derivative arrays (hillshade, slope, profile_curvature, tpi, svf, fill_difference)

    Returns:
        (input_patches, label_patches) each of shape (N, C, H, W) / (N, 1, H, W)
    """
    t0 = time.perf_counter()
    log.info("unet_patch_extraction_start", dem_shape=list(dem.shape), patch_size=patch_size, positive_centers=len(positive_centers), n_negatives=n_negatives)
    if rng is None:
        rng = np.random.default_rng(42)
    h, w = dem.shape
    half = patch_size // 2
    hs = derivatives.get("hillshade", np.zeros_like(dem))
    sl = derivatives.get("slope", np.zeros_like(dem))
    curv = derivatives.get("profile_curvature", np.zeros_like(dem))
    tpi = derivatives.get("tpi", np.zeros_like(dem))
    svf = derivatives.get("svf", np.zeros_like(dem))
    missing_derivs = [k for k in ("hillshade", "slope", "profile_curvature", "tpi", "svf") if k not in derivatives]
    if missing_derivs:
        log.warning("unet_missing_derivatives", missing=missing_derivs, using_zeros=True)
    def normalize(arr):
        vmin, vmax = np.nanmin(arr), np.nanmax(arr)
        if vmax - vmin < 1e-10:
            return np.zeros_like(arr)
        return (arr - vmin) / (vmax - vmin)
    channels = np.stack([normalize(hs), normalize(sl), normalize(curv), normalize(tpi), normalize(svf)])
    fill_diff = derivatives.get("fill_difference", np.zeros_like(dem))
    label_full = (fill_diff > 0.5).astype(np.float32)
    inputs = []
    labels = []
    skipped_oob = 0
    # Positive patches centered on known features
    for cy, cx in positive_centers:
        if cy - half < 0 or cy + half > h or cx - half < 0 or cx + half > w:
            skipped_oob += 1
            continue
        inp = channels[:, cy - half:cy + half, cx - half:cx + half]
        lbl = label_full[cy - half:cy + half, cx - half:cx + half]
        inputs.append(inp)
        labels.append(lbl[np.newaxis])
    if skipped_oob:
        log.debug("unet_positive_patches_skipped_oob", skipped=skipped_oob)
    # Negative patches
    for _ in range(n_negatives):
        cy = rng.integers(half, h - half)
        cx = rng.integers(half, w - half)
        inp = channels[:, cy - half:cy + half, cx - half:cx + half]
        lbl = np.zeros((1, patch_size, patch_size), dtype=np.float32)
        inputs.append(inp)
        labels.append(lbl)
    if not inputs:
        log.warning("unet_patch_extraction_empty", positive_centers=len(positive_centers), n_negatives=n_negatives, skipped_oob=skipped_oob)
        return np.empty((0, 5, patch_size, patch_size), dtype=np.float32), \
               np.empty((0, 1, patch_size, patch_size), dtype=np.float32)
    elapsed = round(time.perf_counter() - t0, 2)
    n_pos = len(positive_centers) - skipped_oob
    log.info("unet_patch_extraction_complete", total_patches=len(inputs), positives=n_pos, negatives=n_negatives, patch_size=patch_size, elapsed_s=elapsed)
    return np.array(inputs, dtype=np.float32), np.array(labels, dtype=np.float32)
