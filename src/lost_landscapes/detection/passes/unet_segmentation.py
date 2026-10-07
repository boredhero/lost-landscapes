"""U-Net semantic segmentation pass on stacked DEM derivative channels.

Performs pixel-level segmentation to identify depression/cave/mine features.
Input: 5-channel tensor (hillshade, slope, profile_curvature, TPI, SVF).
Output: probability mask → thresholded → connected components → candidates.

Based on Rafique et al. (2022) — sinkhole IoU 45.38% on DEM gradient.
Requires PyTorch (GPU optional, ROCm or CUDA).
"""

import time
from pathlib import Path

import numpy as np
from scipy.ndimage import label as ndimage_label
from shapely.geometry import Point

from lost_landscapes.config import settings
from lost_landscapes.detection.base import Candidate, DetectionPass, FeatureType, PassInput
from lost_landscapes.detection.registry import register_pass
from lost_landscapes.utils.log_manager import log


def _build_unet():
    """Build a simple U-Net architecture in PyTorch.

    Returns the model class (not instantiated).
    """
    import torch
    import torch.nn as nn

    class DoubleConv(nn.Module):
        def __init__(self, in_ch, out_ch):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, 3, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, 3, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
            )
        def forward(self, x):
            return self.conv(x)

    class UNet(nn.Module):
        def __init__(self, in_channels=5, out_channels=1):
            super().__init__()
            self.enc1 = DoubleConv(in_channels, 64)
            self.enc2 = DoubleConv(64, 128)
            self.enc3 = DoubleConv(128, 256)
            self.enc4 = DoubleConv(256, 512)
            self.bottleneck = DoubleConv(512, 1024)

            self.up4 = nn.ConvTranspose2d(1024, 512, 2, stride=2)
            self.dec4 = DoubleConv(1024, 512)
            self.up3 = nn.ConvTranspose2d(512, 256, 2, stride=2)
            self.dec3 = DoubleConv(512, 256)
            self.up2 = nn.ConvTranspose2d(256, 128, 2, stride=2)
            self.dec2 = DoubleConv(256, 128)
            self.up1 = nn.ConvTranspose2d(128, 64, 2, stride=2)
            self.dec1 = DoubleConv(128, 64)

            self.final = nn.Conv2d(64, out_channels, 1)
            self.pool = nn.MaxPool2d(2)

        def forward(self, x):
            e1 = self.enc1(x)
            e2 = self.enc2(self.pool(e1))
            e3 = self.enc3(self.pool(e2))
            e4 = self.enc4(self.pool(e3))
            b = self.bottleneck(self.pool(e4))

            d4 = self.dec4(torch.cat([self.up4(b), e4], dim=1))
            d3 = self.dec3(torch.cat([self.up3(d4), e3], dim=1))
            d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
            d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))

            return torch.sigmoid(self.final(d1))

    return UNet


def _prepare_input_tensor(
    dem: np.ndarray,
    derivatives: dict[str, np.ndarray],
    resolution: float,
) -> np.ndarray:
    """Stack 5 derivative channels into a normalized tensor.

    Channels: hillshade, slope, profile_curvature, tpi_15m, svf
    """
    hs = derivatives.get("hillshade")
    sl = derivatives.get("slope")
    curv = derivatives.get("profile_curvature")
    tpi = derivatives.get("tpi") or derivatives.get("tpi_15m")
    svf = derivatives.get("svf")

    if any(d is None for d in [hs, sl, curv, tpi, svf]):
        return np.zeros((5, dem.shape[0], dem.shape[1]), dtype=np.float32)

    # Normalize each channel to [0, 1]
    def normalize(arr: np.ndarray) -> np.ndarray:
        vmin, vmax = np.nanmin(arr), np.nanmax(arr)
        if vmax - vmin < 1e-10:
            return np.zeros_like(arr)
        return (arr - vmin) / (vmax - vmin)

    channels = np.stack([
        normalize(hs),
        normalize(sl),
        normalize(curv),
        normalize(tpi),
        normalize(svf),
    ], axis=0).astype(np.float32)  # shape: (5, H, W)

    return channels


@register_pass
class UNetSegmentationPass(DetectionPass):
    """Semantic segmentation on stacked DEM derivatives using U-Net."""

    @property
    def name(self) -> str:
        return "unet_segmentation"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def required_derivatives(self) -> list[str]:
        return ["hillshade", "slope", "profile_curvature", "tpi_15m", "svf"]

    @property
    def requires_gpu(self) -> bool:
        return True

    def _load_model(self, model_path: Path | None = None):
        """Load trained U-Net weights."""
        try:
            import torch
        except ImportError:
            log.warning("unet_pass_pytorch_not_available", reason="import_error")
            return None
        UNet = _build_unet()
        model = UNet(in_channels=5, out_channels=1)
        if model_path is None:
            model_path = settings.models_dir / "unet_sinkhole_v1.pt"
        if model_path.exists():
            t_load = time.perf_counter()
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.load_state_dict(torch.load(model_path, map_location=device))
            model = model.to(device)
            model.eval()
            load_elapsed = time.perf_counter() - t_load
            log.info("unet_model_loaded", model_path=str(model_path), device=str(device), load_ms=round(load_elapsed * 1000, 1))
            return model
        log.warning("unet_pass_model_not_found", model_path=str(model_path), reason="returning_none")
        return None

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("unet_pass_start", version=self.version)
        try:
            import torch
        except ImportError:
            log.warning("unet_pass_pytorch_not_available", reason="import_error_returning_empty")
            return []
        config = input_data.config
        patch_size = config.get("patch_size", 256)
        overlap = config.get("overlap", 64)
        threshold = config.get("threshold", 0.5)
        min_area_pixels = config.get("min_area_pixels", 10)
        model_path = config.get("model_path")
        log.debug("unet_pass_config", patch_size=patch_size, overlap=overlap, threshold=threshold, min_area_pixels=min_area_pixels)
        model = self._load_model(Path(model_path) if model_path else None)
        if model is None:
            log.warning("unet_pass_no_model", reason="returning_empty")
            return []
        resolution = abs(input_data.transform[0])
        dem = input_data.dem
        # Prepare multi-channel input
        channels = _prepare_input_tensor(dem, input_data.derivatives, resolution)
        _, h, w = channels.shape
        log.debug("unet_pass_input_prepared", height=h, width=w, channels=channels.shape[0])
        device = next(model.parameters()).device
        # Tile into overlapping patches, run inference, stitch
        prob_map = np.zeros((h, w), dtype=np.float32)
        count_map = np.zeros((h, w), dtype=np.float32)
        stride = patch_size - overlap
        num_patches = 0
        t_infer = time.perf_counter()
        with torch.no_grad():
            for row in range(0, h - patch_size + 1, stride):
                for col in range(0, w - patch_size + 1, stride):
                    patch = channels[:, row:row + patch_size, col:col + patch_size]
                    tensor = torch.from_numpy(patch).unsqueeze(0).to(device)
                    pred = model(tensor).squeeze().cpu().numpy()
                    prob_map[row:row + patch_size, col:col + patch_size] += pred
                    count_map[row:row + patch_size, col:col + patch_size] += 1
                    num_patches += 1
        inference_elapsed = time.perf_counter() - t_infer
        log.info("unet_pass_inference_complete", patches=num_patches, device=str(device), inference_ms=round(inference_elapsed * 1000, 1))
        # Average overlapping predictions
        count_map = np.maximum(count_map, 1)
        prob_map /= count_map
        # Threshold and extract connected components
        binary = prob_map > threshold
        if not np.any(binary):
            elapsed = time.perf_counter() - t0
            log.info("unet_pass_complete", candidates=0, reason="no_pixels_above_threshold", elapsed_s=elapsed)
            return []
        labeled, num_features = ndimage_label(binary)
        log.debug("unet_pass_labeling", raw_features=num_features)
        candidates = []
        for i in range(1, num_features + 1):
            mask = labeled == i
            if np.sum(mask) < min_area_pixels:
                continue
            rows, cols = np.where(mask)
            cy, cx = float(np.mean(rows)), float(np.mean(cols))
            geo_x, geo_y = input_data.transform * (cx, cy)
            mean_prob = float(np.mean(prob_map[mask]))
            area_m2 = float(np.sum(mask)) * resolution * resolution
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    score=mean_prob,
                    feature_type=FeatureType.SINKHOLE,
                    morphometrics={
                        "unet_mean_prob": mean_prob,
                        "area_m2": area_m2,
                    },
                    metadata={"classifier": "unet", "model_version": "v1"},
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("unet_pass_complete", candidates=len(candidates), elapsed_s=elapsed)
        return candidates
