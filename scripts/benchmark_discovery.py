"""Bounded synthetic CPU/memory timing; not an accuracy benchmark."""
import argparse
import json
import resource
import time

import numpy as np
from rasterio.transform import from_origin

import lost_landscapes.detection.passes  # noqa: F401
from lost_landscapes.detection.geometry_support import PASSES
from lost_landscapes.detection.runner import PassRunner

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--size', type=int, default=1000, choices=range(200, 2001), metavar='200..2000')
args = parser.parse_args()
y, x = np.mgrid[:args.size, :args.size]
c = args.size // 2
dem = (100 + .02*x + 4*np.exp(-((x-c)**2+(y-c)**2)/50)).astype('float32')
started = time.perf_counter()
candidates = PassRunner(sorted(PASSES)).run_on_array(dem, from_origin(500000,4400000,1,1), 32617)
print(json.dumps({'cells':int(dem.size), 'seconds':round(time.perf_counter()-started,3),
                  'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
                  'candidates':len(candidates), 'families':sorted({c.feature_type.value for c in candidates}),
                  'scope':'synthetic CPU timing only; includes shared preprocessing'}, indent=2))
