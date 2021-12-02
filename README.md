# jlambert-auto-floorplan

Code for the Auto-Floorplan (AFP) 2021 Internship project within RMX group.

Author: John Lambert

# Repository Structure

Code is organized under the `afp` directory as follows:
- `afp`:
    - `algorithms`: graph and SfM related algorithms, e.g. rotation averaging, Pose(2) SLAM, spanning tree computation, cycle consistency
    - `common`: shared classes for room layout data, WDO objects, and 2d pose graphs
    - `configs`: Hydra config files for model training
    - `dataset`: dataloaders
    - `models`: CNN model architectures, implemented in Pytorch
    - `utils`: utilities for rasterization, rendering graphs, Sim(3) alignment, precision/recall computation, and more.


# Dependencies

We use Conda to manage dependencies. Please install the environment on Linux using:
```bash
conda env create -f environment_linux.yml
```
or on Mac
```bash
conda env create -f environment_mac.yml
```

We use the [`GTSAM`](https://github.com/borglab/gtsam) library for back-end SLAM/pose graph optimization. Pre-built python wheels for `GTSAM` are available for download [here](https://github.com/borglab/gtsam-manylinux-build/actions/runs/1482405025) on Github under "Artifacts" (there is no need to build GTSAM from scratch). The GTSAM libraries on `pypi` are out of date. You must be logged in to github.com in order to be able to download them.  If you're not logged in, it shows you them, but you can't download them.

You should use the Python 3.8 wheel, either looking for a URL with the name (for Linux):
```
gtsam-4.1.0-cp38-cp38-manylinux2014_x86_64.whl
```
or for Mac:
```
wheels-macos-python@3.8
```

Then, make sure you are within the conda environment (`afp-v1`), and install the Python wheel for GTSAM via 
```
pip install /path/to/wheel/file.whl
```

Install GTSFM:
```bash
cd ..
git clone https://github.com/borglab/gtsfm.git
cd gtsfm
pip install -e .
```


**Rendering Training/Testing Data** If you'd like to render training or testing data, clone the `HoHoNet` repo.

**Libraries for evaluation** We use `AvgMeter` classes from `mseg-semantic`. Install as follows:

```bash
git clone https://github.com/mseg-dataset/mseg-semantic.git
cd mseg-semantic
pip install -e .
```

**Notes about libraries used**
- We use Facebook's `hydra` library for configuration files.
- We use the [`rdp`](https://github.com/fhirschmann/rdp) library for polygon simplification.


## Installation
To install the Auto-Floorplan (`afp`) library, run:
```
pip install -e .
```

## Verify Installation

Run the unit tests:
```bash
pytest tests/
```

## Download ZInD

Register on Bridge API and request access. Then copy the server token and run the following commands:

```bash
git clone https://github.com/zillow/zind.git
cd zind
python download_data.py --num_process 10 --verbose --output_folder {SAVE_DIR} --server_token {BRIDGE_API_SERVER_TOKEN}
```

For example, `SAVE_DIR` could be `/mnt/data/johnlam/zind_bridgeapi_2021_10_05`, and `BRIDGE_API_SERVER_TOKEN` could be a 32-character alphanumeric sequence.

On DGX, you can find `ZInD` stored here:
`/mnt/data/johnlam/zind_bridgeapi_2021_10_05`

## Running Reconstruction

Make sure you are within the conda environment (`afp-v1`).

Download and unzip the Madori-V1 HorizonNet predictions from [Google Drive here](https://drive.google.com/file/d/1VBTBYIaFSHDtP31_FnM6vII3_p1On3tE/view?usp=sharing).

Download the (prod pano GUID) -> (ZInD pano filename) mapping information from [Google Drive here](https://drive.google.com/file/d/1ALPLDWPA8K7taNuxReOt0RiaJ1AlIEY1/view?usp=sharing).

```bash
unzip {}
RMX_MADORI_V1_PREDICTIONS_DIRPATH = {}
```
First, set `RMX_MADORI_V1_PREDICTIONS_DIRPATH` inside `afp/dataset/hnet_prediction_loader.py`.
Next, set `PANO_MAPPING_TSV_FPATH` also inside `afp/dataset/hnet_prediction_loader.py`.

Run SALVe model inference by first generating alignment hypotheses:
```bash
python scripts/export_alignment_hypotheses.py --num_processes {NUM. DESIRED PROCS.} \
    --raw_dataset_dir {PATH TO ZIND} --hypotheses_save_root {DIRECTORY WHERE TO DUMP OUTPUT}
```

Next, clone the repository: 
```bash
git clone https://gitlab.zgtools.net/johnlam/jlambert-auto-floorplan.git
```

Set `SALVE_REPO_FPATH` to wherever you have cloned `jlambert-auto-floorplan`



Run HoHoNet inference and render BEV texture maps:
```bash
cd ..
git clone https://github.com/sunset1995/HoHoNet.git
cd HoHoNet
```

Now download the HoHoNet model here: 
```bash
./{SALVE_REPO_FPATH}/scripts/download_monodepth_model.sh
```

Now run:
```bash
export PYTHONPATH=./

python {SALVE_REPO_DIRPATH}/scripts/render_dataset_bev.py --num_processes {NUM. DESIRED PROCS.} \
    --raw_dataset_dir {PATH TO ZIND} \
    --hypotheses_save_root {PATH TO PRE-GENERATED ALIGNMENT HYPOTHESES} \
    --depth_save_root {PATH TO WHERE DEPTH MAPS WILL BE SAVED TO}\
    --bev_save_root {PATH WHERE BEV TEXTURE MAPS WILL BE SAVED TO}
```

If you see an error message like:
```
HoHoNet's lib could not be loaded, skipping...
Exception:  No module named 'lib'
```
then you have not configured `HoHoNet` properly above.

Next, send the pairs of BEV texture maps to the model for scoring:
```bash
python scripts/test.py --gpu_ids {COMMA SEPARATED GPU ID LIST}
```

Now, pass the front-end measurements to SfM:
```bash
python scripts/run_sfm.py --raw_dataset_dir {PATH TO ZIND}
```

## Pretrained Models

- Custom HorizonNet W/D/O & Layout w/ photometric info:
- Rasterized layout only:
- GT WDO:

## Training a model

```bash
python scripts/train.py --gpu_ids {COMMA SEPARATED GPU ID LIST} \
    --config_name {FILE NAME OF YAML CONFIG under afp/configs/}
```

## TODOs:

- Maybe use different schema for Madori-V1 files.
- Find missing Madori-V1.
- 

Additional Notes:
- Batch 1 of Madori predictions: [here, on Google Drive](https://drive.google.com/drive/folders/1A7N3TESuwG8JOpx_TtkKCy3AtuTYIowk?usp=sharing)
(in batch 1 of the predictions, it looks like new_home_id matched to floor_map_guid_new. in batch 2, that matches to floormap_guid_prod)

## Run Static Analysis of Codebase

```bash
flake8 --max-line-length 120 --ignore E201,E202,E203,E231,W291,W293,E303,W391,E402,W503,E731 afp
```

```bash
pytest tests --cov afp --ignore tests/test_export_alignment_hypotheses.py
coverage report
```

## Running SfM Baselines

In the paper, we compare with OpenMVG and OpenSfM. You can run these baselines yourself as follows.

**OpenSfM**: First, clone the repository:
```bash
git clone https://github.com/mapillary/OpenSfM.git
cd OpenSfM
```
Now, build the library/binaries, as described [here](https://opensfm.org/docs/building.html).

Next, inside the `OpenSfM` directory, now run:
```bash
python {SALVE_REPO_DIRPATH}/afp/baselines/opensfm.py
```

**OpenMVG**: 
```bash
python {SALVE_REPO_DIRPATH}/afp/baselines/openmvg.py
```
