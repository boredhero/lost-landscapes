# Evaluation data and labeling, version 1

Delivery B establishes an offline contract and a small point-scoring baseline.
It does not supply reviewed real-world labels or validate the archaeological
accuracy of the existing detector. The example files are entirely synthetic,
including their survey fingerprint, reviewer and evidence references. Their
Pittsburgh-area coordinates do not identify actual sites.

## Run it

From the repository root, after installing the locked Python dependencies:

```sh
uv run --no-sync python -m lost_landscapes.benchmark validate tests/fixtures/benchmark/synthetic-manifest.json
uv run --no-sync python -m lost_landscapes.benchmark score-points tests/fixtures/benchmark/synthetic-manifest.json tests/fixtures/benchmark/synthetic-predictions.json
uv run --no-sync python -m lost_landscapes.benchmark schema manifest
uv run --no-sync python -m lost_landscapes.benchmark schema predictions
```

Commands print JSON to stdout and failures to stderr with a nonzero exit status.
They require no database, worker, network access or DEM processing tools. JSON
Schemas describe the serialized contract; the validation command additionally
checks geometry, references and spatial isolation.

The example produces one raised-feature hit, two raised-feature false positives
(one duplicate and one wrong-family suggestion), one missed raised feature and
one missed depression. One suggestion near an unresolved label is excluded.
An empty prediction list produces three misses, not skipped successes.

## Manifest contract

`src/lost_landscapes/benchmark/models.py` is the executable schema. Unknown fields
and unsupported schema versions are rejected rather than silently discarded.

| Record | Required meaning |
| --- | --- |
| Dataset | Stable ID, explicit dataset version, `synthetic` or `reviewed-data` purpose, description, protocol, surveys, regions and labels. |
| Survey | Source reference, SHA-256 of the exact source artifact or documented source bundle manifest, license, resolution and footprint. Acquisition date and vertical datum are explicitly nullable; unknown values must remain unknown. |
| Protocol | Local projected metre CRS, point tolerance with rationale, spatial split buffer, and named/date-stamped split lock with rationale. |
| Region | Polygon, referenced survey IDs, `train`/`validation`/`test` split, independence group and per-family review records. |
| Family review | Reviewer, review date, evidence references and either `partial` or `exhaustive` coverage of that family throughout the region. No review is assumed from a survey footprint. |
| Label | Stable label and physical-feature IDs, region, morphology family, geometry and chronological review history. |
| Label review | Consecutive revision number, `present`/`absent`/`uncertain` assessment, reviewer/date, evidence, observed morphology, proposed interpretation, separate visibility and interpretation confidence, and nullable dating evidence. |

Families are `raised`, `depression`, `linear`, `enclosure`, `geological` and
`unclassified`. These describe evaluation categories, not verified archaeological
origins. A depression is not automatically a cave; a raised feature is not
automatically a burial mound.

All geometries use WGS84 longitude then latitude, in two dimensions. Points,
LineStrings and valid closed Polygons are accepted for labels. Regions and survey
footprints are Polygons. Distances and area are computed in the protocol's local
projected metre CRS, never from display pixels or terrain exaggeration. The
validator rejects angular/foot-based CRSs, common global Mercator CRSs, and regions
outside the declared projection's area of use. The dataset curator must still
choose a suitable low-distortion projection and justify it for the study area.

Survey source references and hashes are recorded, not fetched or independently
verified by this command. Verify source bytes and evidence access when preparing
a real dataset. `valid: true` means contract consistency, not scientific truth.

## Splits, revisions and negatives

1. Choose independent landscape units before tuning. Keep connected earthwork,
   road, drainage or extraction systems within the same independence group even
   when they span source tiles. Every region in that group must use one split.
2. Regions may not overlap or share boundaries. Different splits require at least
   the declared spatial buffer; the buffer must be at least twice the point
   tolerance. Increase it to account for terrain neighborhoods, detector context
   and spatial correlation. The mathematical minimum is not a universal scientific
   separation distance.
3. Keep one physical feature in one label. The validator rejects duplicate IDs,
   repeated physical-feature IDs, coincident same-family geometries, broken
   references and labels outside their region. It cannot infer that two differently
   named, differently drawn objects are actually the same feature; adjudicate them.
4. Preserve old manifest versions and review history. A new assessment appends a
   review; the last review controls the current assessment. Geometry, family,
   evidence, splits or protocol changes require a new dataset version and archived
   previous artifact. The CLI cannot establish that an externally edited history
   was preserved, or enforce organizational access to held-out data.
5. Partial or missing review does not make unlabeled ground negative. Mark a family
   exhaustive only after its entire region has been reviewed and all identified
   positives and unresolved observations recorded. A reviewed region with no
   positive labels is a valid negative area. An `absent` label documents a rejected
   lookalike; it does not establish exhaustive review of surrounding ground.
6. Choose matching tolerances and score thresholds using training/validation data;
   lock them before running the held-out test. Do not repeatedly inspect test
   results while tuning. The baseline consumes an already-selected shortlist and
   does not tune thresholds or interpret scores as calibrated probabilities.

Predictions must name the exact dataset ID/version, canonical manifest SHA-256,
split, evaluated families, algorithm/version and configuration. The digest is
printed by `validate`; it is stable across JSON formatting changes. Reports also
include the canonical prediction digest. A mismatched manifest is rejected even
if its dataset version was accidentally left unchanged.

## Point baseline accounting

Within each exhaustively reviewed region/family, match predictions to present
point labels using maximum-cardinality one-to-one matching, then minimum total
projected distance. Only distances within the declared tolerance qualify. IDs
are sorted for repeatable processing. A prediction cannot match a different family
or satisfy multiple labels.

- Unmatched present labels count as false negatives, including an empty result set.
- Unmatched predictions in reviewed areas count as false positives. Extra
  predictions near an already matched label are additionally reported as duplicates.
- Wrong-family suggestions count as false positives in their predicted family
  and do not rescue misses in the true family when both families are evaluated.
- Uncertain labels exclude their geometry buffered by the matching tolerance
  from scoring. Predictions and present labels in that neighborhood are listed
  explicitly as excluded; the area is removed from the denominator.
- Predictions in partially reviewed/unreviewed regions are listed as excluded.
  Predictions outside the selected split are errors, not silently ignored results.
- Precision and recall use null for an empty denominator. A family with no
  reviewed area is marked `no_reviewed_area`; this is not a successful evaluation.

Reports contain counts, matched IDs/distances, missed IDs, false-positive and
duplicate IDs, exclusions, precision, recall, reviewed area and false positives
per square kilometre. The matching matrix is capped at one million pairs per
region/family. Large evaluations must use the later scalable harness, not silently
drop candidates to fit this baseline.

Line and polygon labels can be recorded now, but present nonpoint labels in a
scored region/family cause an explicit error. They are never reduced to centroids
to inflate a point metric. Footprint overlap, line/network coverage, regional
stratification, uncertainty intervals, reviewer effort and automated detector-run
capture belong to the later evaluation harness (deliveries G/H).

## Candidate real-data cohorts

These are selection targets, not downloaded or reviewed benchmark datasets:

| Cohort | Initial selection | Needed before inclusion |
| --- | --- | --- |
| Engineering baseline | The existing imported Western Pennsylvania/Pittsburgh DEM footprint. | Inspect source quality and provenance; choose separated regions; review complete family-specific areas. Existing browser smoke tests are not labels. |
| Industrial/mining and old routes | Separate Western Pennsylvania landscape units with independently accessible historical/mining/transport evidence. | Confirm source access and licensing, coverage, survey metadata and reviewer agreement; keep connected workings/routes in one split. |
| Natural terrain and difficult negatives | Rural wooded and drainage-dominated units outside the first landscape systems, including modern disturbance lookalikes. | Review positives as well as negatives, record uncertain origins and incomplete visibility, and avoid treating inventory absence as proof of absence. |
| Transfer evaluation | A further region with compatible LiDAR and independently reviewable evidence, selected after the initial protocol is exercised. | Choose the region and lock its split before regional tuning; document how conditions differ. |

No real-data accuracy target is claimed yet. Begin with the existing detector as
a baseline after its output can be reproducibly exported. The research rationale
and primary references remain in [the development plan](development-plan.md#research-basis).
