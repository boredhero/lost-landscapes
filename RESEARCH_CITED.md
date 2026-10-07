# Research Cited

Papers, datasets, and resources used to design and implement Lost Landscapes.

---

## Sinkhole & Depression Detection

### Fill-Difference / Sink-Fill Method
- **Wall, J., Bohnenstiehl, D.R., Wegmann, K.W. (2016)** — "Morphometric comparisons between automated and manual karst depression inventories." *Natural Hazards* 85(2). 93% detection rate at Mammoth Cave.
- **Pardo-Iguzquiza, E., Duran Valsero, J.J., Dowd, P.A. (2013)** — "Automatic detection and delineation of karst terrain depressions." *Acta Carsologica* 42(1). [DOI: 10.3986/ac.v42i1.637](https://doi.org/10.3986/ac.v42i1.637)

### Contour Tree / Level-Set Methods
- **Wu, Q. (2016)** — "Automated delineation of karst sinkholes from LiDAR-derived DEMs." *Geomorphology* 266. [DOI: 10.1016/j.geomorph.2016.05.006](https://doi.org/10.1016/j.geomorph.2016.05.006)
- **Wu, Q., Lane, C.R., et al. (2019)** — "Efficient Delineation of Nested Depression Hierarchy in DEMs." *JAWRA* 55(2):354-368. [DOI: 10.1111/1752-1688.12689](https://doi.org/10.1111/1752-1688.12689). Released as the [`lidar` Python package](https://github.com/opengeos/lidar).

### Morphometric Analysis
- **Kim, Y.J., Sharma, A., Wasklewicz, T. (2019)** — "Sinkhole Detection and Characterization Using LiDAR-Derived DEM with Logistic Regression." *Remote Sensing* 11(13):1592. AUC=0.90. [https://www.mdpi.com/2072-4292/11/13/1592](https://www.mdpi.com/2072-4292/11/13/1592)
- **Telbisz, T. et al. (2024)** — "LiDAR-Based Morphometry of Dolines in Aggtelek Karst." *Remote Sensing* 16(5):737. Introduced k-parameter for 3D doline shape. [https://www.mdpi.com/2072-4292/16/5/737](https://www.mdpi.com/2072-4292/16/5/737)
- **Kobal, M., et al. (2015)** — "Using Lidar Data to Analyse Sinkhole Characteristics Relevant for Understory Vegetation." *PLoS ONE*. [DOI: 10.1371/journal.pone.0122070](https://doi.org/10.1371/journal.pone.0122070)

### Water Flow / Process-Based
- **Hofierka, J., et al. (2018)** — "Identification of karst sinkholes using airborne laser scanning data and water flow analysis." *Geomorphology* 308:265+. [DOI: 10.1016/j.geomorph.2018.02.004](https://doi.org/10.1016/j.geomorph.2018.02.004)

---

## Cave Entrance Detection

### Local Relief Models
- **Moyes, H., Montgomery, S. (2019)** — "Locating Cave Entrances Using Lidar-Derived Local Relief Modeling." *Geosciences* 9(2):98. 80% of predicted horizontal entrances confirmed. [DOI: 10.3390/geosciences9020098](https://doi.org/10.3390/geosciences9020098)

### Visualization Techniques
- **Zakšek, K. et al. (2011)** — "Sky-View Factor as a Relief Visualization Technique." *Remote Sensing* 3(2):398. [https://www.mdpi.com/2072-4292/3/2/398](https://www.mdpi.com/2072-4292/3/2/398)
- **(2024)** — "Sky-view factor enhanced doline delineation: A comparative methodological review." *Geomorphology*. [https://www.sciencedirect.com/science/article/abs/pii/S0169555X24003398](https://www.sciencedirect.com/science/article/abs/pii/S0169555X24003398)

---

## Mine Entrance Detection

- **USGS** — "Database of historical anthracite coal-mining infrastructure, Lackawanna syncline, Pennsylvania." [https://www.usgs.gov/data/database-historical-anthracite-coal-mining-infrastructure-northern-end-lackawanna-syncline](https://www.usgs.gov/data/database-historical-anthracite-coal-mining-infrastructure-northern-end-lackawanna-syncline)
- **GRM** — "The Use of LIDAR Technology to Locate Unrecorded Coal Mines." [https://www.grm-uk.com/finding-unrecorded-coal-mines-using-lidar-technology/](https://www.grm-uk.com/finding-unrecorded-coal-mines-using-lidar-technology/)
- **(2023)** — "Convolutional neural networks for accurate identification of mining remains from UAV-derived images." *Applied Intelligence*. [https://link.springer.com/article/10.1007/s10489-023-05161-8](https://link.springer.com/article/10.1007/s10489-023-05161-8)

---

## Machine Learning Approaches

### Random Forest
- **Zhu, J., Pierskalla, W.P. (2016)** — "Applying a weighted random forests method to extract karst sinkholes from LiDAR data." *Journal of Hydrology* 533:343+. [DOI: 10.1016/j.jhydrol.2015.12.012](https://doi.org/10.1016/j.jhydrol.2015.12.012)
- **Zhu, J., Crawford, M.M. et al. (2020)** — "Using machine learning to identify karst sinkholes from LiDAR-derived topographic depressions." *Journal of Hydrology*. Neural nets: 97% of sinkholes found by inspecting 27% of candidates. RF AUC=0.92. [DOI: 10.1016/j.jhydrol.2020.125049](https://doi.org/10.1016/j.jhydrol.2020.125049)

### Deep Learning
- **Rafique, M.U., Zhu, J., Jacobs, N. (2022)** — "Automatic Segmentation of Sinkholes Using a Convolutional Neural Network." *Earth and Space Science* 9(2). U-Net on DEM gradient, IoU=45.38%. [DOI: 10.1029/2021EA002195](https://doi.org/10.1029/2021EA002195). Code: [https://mvrl.github.io/SinkSeg/](https://mvrl.github.io/SinkSeg/), Dataset: [https://doi.org/10.5281/zenodo.5789436](https://doi.org/10.5281/zenodo.5789436)
- **(2024)** — "Detection and automatic identification of loess sinkholes from LiDAR point clouds and deep learning." *Geomorphology*. PointNet++ on raw 3D point clouds. [https://www.sciencedirect.com/science/article/abs/pii/S0169555X24003544](https://www.sciencedirect.com/science/article/abs/pii/S0169555X24003544)
- **(2025)** — "Sinkhole detection via deep learning using DEM images." *Natural Hazards*. [https://link.springer.com/article/10.1007/s11069-025-07127-0](https://link.springer.com/article/10.1007/s11069-025-07127-0)
- **(2023)** — "SinkholeNet: A novel RGB-slope sinkhole dataset and deep weakly-supervised learning framework." *Egyptian Journal of Remote Sensing*. [https://www.sciencedirect.com/science/article/pii/S1110982323000881](https://www.sciencedirect.com/science/article/pii/S1110982323000881)

### Point Cloud Deep Learning
- **Thomas, H. et al. (2019)** — "KPConv: Flexible and Deformable Convolution for Point Clouds." *ICCV*. [https://arxiv.org/abs/1904.08889](https://arxiv.org/abs/1904.08889). Code: [https://github.com/HuguesTHOMAS/KPConv](https://github.com/HuguesTHOMAS/KPConv)
- **(2025)** — "Multi-KPConv: deep learning-based LiDAR point cloud ground point extraction for complex terrains." *Int. J. Digital Earth*. [https://www.tandfonline.com/doi/full/10.1080/17538947.2025.2556235](https://www.tandfonline.com/doi/full/10.1080/17538947.2025.2556235)

---

## Terrain Analysis Algorithms

### Slope & Curvature
- **Horn, B.K.P. (1981)** — "Hill shading and the reflectance map." *Proceedings of the IEEE* 69(1):14-47. Used in GDAL `gdaldem slope/hillshade`.
- **Zevenbergen, L.W. & Thorne, C.R. (1987)** — "Quantitative analysis of land surface topography." *Earth Surface Processes and Landforms* 12(1):47-56. Profile/plan curvature.

### Priority-Flood Depression Filling
- **Barnes, R., Lehman, C., Mulla, D. (2014)** — "Priority-flood: An optimal depression-filling and watershed-labeling algorithm for digital elevation models." *Computers & Geosciences* 62:117-127. Implemented in WhiteboxTools.

### Morphological Reconstruction
- **Vincent, L. (1993)** — "Morphological grayscale reconstruction in image analysis." *IEEE Transactions on Image Processing* 2(2):176-201.

---

## Multi-Temporal / Active Detection
- **(2021)** — "The Detection of Active Sinkholes by Airborne Differential LiDAR DEMs and InSAR." *Remote Sensing* 13(16):3261. [https://www.mdpi.com/2072-4292/13/16/3261](https://www.mdpi.com/2072-4292/13/16/3261)

---

## Ground Truth & Validation Datasets

### Pennsylvania
- **PASDA** — Pennsylvania Spatial Data Access. 111,000+ karst feature points across 14 counties. [https://www.pasda.psu.edu/](https://www.pasda.psu.edu/)
- **PA DEP AML Inventory** — 11,249 abandoned mine sites. [https://www.pa.gov/agencies/dep/programs-and-services/mining/abandoned-mine-reclamation/aml-program-information/](https://www.pa.gov/agencies/dep/programs-and-services/mining/abandoned-mine-reclamation/aml-program-information/)
- **USGS OFR 03-471** — Digital Karst Density Layer for PA. [https://pubs.usgs.gov/of/2003/of03-471/](https://pubs.usgs.gov/of/2003/of03-471/)
- **PA Geological Survey** — Sinkhole data via PaGEODE. [https://www.pa.gov/agencies/dcnr/conservation/geology/geologic-hazards/sinkholes](https://www.pa.gov/agencies/dcnr/conservation/geology/geologic-hazards/sinkholes)

### West Virginia
- **WVACS** — West Virginia Association for Cave Studies. 350+ miles of surveyed cave passages. [https://wvacs.org/](https://wvacs.org/)
- **WVGES** — Coal Bed Mapping Project, Mine Map Database (80,000+ maps). [https://www.wvgs.wvnet.edu/](https://www.wvgs.wvnet.edu/)
- **WV Cave Conservancy** — McClung Cave, Friars Hole preserves. [https://wvcc.net/](https://wvcc.net/)

### New York
- **USGS SIR 2020-5030** — Statewide Assessment of Karst Aquifers in New York. 5,023 closed depressions. [https://www.usgs.gov/publications/statewide-assessment-karst-aquifers-new-york-inventory-closed-depression-and-focused](https://www.usgs.gov/publications/statewide-assessment-karst-aquifers-new-york-inventory-closed-depression-and-focused)

### Ohio
- **Ohio DNR** — Ohio Karst Areas Map. [https://dam.assets.ohio.gov/image/upload/ohiodnr.gov/documents/geology/MiscMap_OhioKarst_2016.pdf](https://dam.assets.ohio.gov/image/upload/ohiodnr.gov/documents/geology/MiscMap_OhioKarst_2016.pdf)
- **Ohio Cave Survey** — [https://ohiocavesurvey.org/](https://ohiocavesurvey.org/)

### North Carolina
- **NC Cave Survey** — 1,500+ documented caves across western NC Blue Ridge region.
- **USGS Professional Paper 577** — Mica Deposits of the Blue Ridge in North Carolina (Lesure, F.G.). Spruce Pine Mining District, 700+ mica and feldspar mines.
- **NC Wildlife Action Plan** — Caves and Mines Section 4.4.1. [https://www.ncwildlife.gov/caves-and-mines-section-441pdf/open](https://www.ncwildlife.gov/caves-and-mines-section-441pdf/open)

### Maryland
- **Maryland Geological Survey (MGS)** — Caves of Maryland (Educational Series Report 3). 53 documented caves. [https://www.mgs.md.gov/geology/caves/caves_in_maryland.html](https://www.mgs.md.gov/geology/caves/caves_in_maryland.html)
- **MGS Karst Hydrogeology** — Hagerstown Valley karst survey, 2,100+ karst features. [https://www.mgs.md.gov/publications/report_pages/RI_73.html](https://www.mgs.md.gov/publications/report_pages/RI_73.html)
- **MGS Sinkholes** — Sinkhole inventory for western Maryland. [https://www.mgs.md.gov/geology/geohazards/sinkholes_in_maryland.html](https://www.mgs.md.gov/geology/geohazards/sinkholes_in_maryland.html)

### Massachusetts
- **USGS Bulletin 744** — "The Lime Belt of Massachusetts." Berkshire County marble and limestone. [https://pubs.usgs.gov/bul/0744/report.pdf](https://pubs.usgs.gov/bul/0744/report.pdf)
- **USGS MRDS** — 160+ mines in Massachusetts (iron, lead, copper, pyrite, mica). [https://mrdata.usgs.gov/mrds/](https://mrdata.usgs.gov/mrds/)

### Louisiana
- **Louisiana Geological Survey** — Subsidence monitoring and salt dome studies. [https://www.lsu.edu/lgs/](https://www.lsu.edu/lgs/)
- **Bayou Corne Sinkhole** — 37-acre active salt dome collapse, Napoleonville Dome, Assumption Parish. Monitored via SORRENTO seismic array (17 stations).
- **NASA JPL** — "That Sinking Feeling." InSAR precursory deformation studies of Gulf Coast subsidence. [https://www.jpl.nasa.gov/news/that-sinking-feeling/](https://www.jpl.nasa.gov/news/that-sinking-feeling/)
- **EarthScope** — Monitoring microearthquakes of energy-storing salt domes in the Southeast US. [https://www.earthscope.org/news/monitoring-microearthquakes-of-energy-storing-salt-domes-in-the-southeast-us/](https://www.earthscope.org/news/monitoring-microearthquakes-of-energy-storing-salt-domes-in-the-southeast-us/)

### California
- **BLM Abandoned Mine Lands** — 25,000+ sites with 66,000+ features (portals, rock dumps) in California. [https://www.doi.gov/ocl/hearings/111/AbandonedMinesInCA_112309](https://www.doi.gov/ocl/hearings/111/AbandonedMinesInCA_112309)
- **USGS MRDS** — 22,000+ California mine records. [https://mrdata.usgs.gov/mrds/](https://mrdata.usgs.gov/mrds/)
- **California Geological Survey** — Historic Gold Mines map (13,500 mine locations). [https://www.conservation.ca.gov/cgs/minerals/gold](https://www.conservation.ca.gov/cgs/minerals/gold)
- **CalGEM Mines Online** — California mine database portal. [https://maps.conservation.ca.gov/mol/index.html](https://maps.conservation.ca.gov/mol/index.html)
- **NPS Lava Beds National Monument** — 700-800 lava tubes, 450 navigable caves. Cave Research Foundation surveys. [https://www.nps.gov/labe/](https://www.nps.gov/labe/)
- **Cave Research Foundation** — Klamath Mountains Project (2018-present), lava tube surveys. [https://www.cave-research.org/](https://www.cave-research.org/)

### National
- **USGS OFR 2014-1156** — "Karst in the United States: A Digital Map Compilation and Database." Shapefiles (269MB). [https://pubs.usgs.gov/of/2014/1156/](https://pubs.usgs.gov/of/2014/1156/)
- **National Mine Map Repository (OSMRE)** — 275,000+ mine maps. [https://www.osmre.gov/programs/national-mine-map-repository](https://www.osmre.gov/programs/national-mine-map-repository)
- **USGS MRDS** — Mineral Resources Data System, national mine/prospect database. [https://mrdata.usgs.gov/mrds/](https://mrdata.usgs.gov/mrds/)

---

## LiDAR Data Sources

- **USGS 3DEP** — 3D Elevation Program. COPC on AWS (`s3://usgs-lidar-public/`). [https://www.usgs.gov/3d-elevation-program](https://www.usgs.gov/3d-elevation-program)
- **Microsoft Planetary Computer** — STAC API for 3DEP COPC discovery. [https://planetarycomputer.microsoft.com/dataset/3dep-lidar-copc](https://planetarycomputer.microsoft.com/dataset/3dep-lidar-copc)
- **PASDA** — PA LiDAR via PAMAP program. [https://www.pasda.psu.edu/](https://www.pasda.psu.edu/)
- **WV GIS** — West Virginia elevation data. [http://data.wvgis.wvu.edu/elevation/](http://data.wvgis.wvu.edu/elevation/)
- **NYS GIS** — New York State LiDAR. [https://gis.ny.gov/lidar](https://gis.ny.gov/lidar)
- **OGRIP** — Ohio Geographically Referenced Information Program. [https://gis1.oit.ohio.gov/geodatadownload/](https://gis1.oit.ohio.gov/geodatadownload/)
- **NC OneMap** — North Carolina statewide LiDAR tile index. [https://www.nconemap.gov/](https://www.nconemap.gov/)
- **MD iMAP** — Maryland enterprise GIS LiDAR portal. [https://imap.maryland.gov/pages/lidar-download](https://imap.maryland.gov/pages/lidar-download)
- **MassGIS** — Massachusetts LiDAR terrain data. [https://www.mass.gov/info-details/massgis-data-lidar-terrain-data](https://www.mass.gov/info-details/massgis-data-lidar-terrain-data)
- **LSU Atlas / LOSCO** — Louisiana statewide LiDAR (5m DEM). [https://atlas.ga.lsu.edu/](https://atlas.ga.lsu.edu/)
- **OpenTopography** — NSF-funded open LiDAR access, extensive California coverage. [https://opentopography.org/](https://opentopography.org/)

---

## Tools & Libraries

- **PDAL** — Point Data Abstraction Library. [https://pdal.io/](https://pdal.io/)
- **GDAL** — Geospatial Data Abstraction Library. `gdaldem` for hillshade, slope, TPI, roughness. [https://gdal.org/](https://gdal.org/)
- **WhiteboxTools** — Geomorphometry tools in Rust. fill_depressions, SVF, LRM, curvature. [https://github.com/jblindsay/whitebox-tools](https://github.com/jblindsay/whitebox-tools)
- **Rasterio** — Python raster I/O. [https://rasterio.readthedocs.io/](https://rasterio.readthedocs.io/)
- **GeoAlchemy2** — SQLAlchemy + PostGIS. [https://geoalchemy-2.readthedocs.io/](https://geoalchemy-2.readthedocs.io/)
- **scikit-learn** — Random Forest classifier. [https://scikit-learn.org/](https://scikit-learn.org/)
- **PyTorch** — U-Net, YOLOv8 (via ROCm). [https://pytorch.org/](https://pytorch.org/)
- **deck.gl** — WebGL map layers. [https://deck.gl/](https://deck.gl/)
- **MapLibre GL JS** — Open-source map rendering. [https://maplibre.org/](https://maplibre.org/)

---

## Caving & Karst Organizations

- **Mid-Atlantic Karst Conservancy** — Harlansburg Cave, LiDAR guide. [https://www.karst.org/](https://www.karst.org/)
- **National Speleological Society** — Tytoona Cave preserve. [https://caves.org/](https://caves.org/)
- **NC Geological Survey** — Part of NC DEQ. [https://ncgs.state.nc.us/](https://ncgs.state.nc.us/)
- **Cave Research Foundation** — Crystal Cave (Sequoia), Lava Beds surveys. [https://www.cave-research.org/](https://www.cave-research.org/)
