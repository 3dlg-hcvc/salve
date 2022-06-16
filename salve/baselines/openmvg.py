"""
https://github.com/openMVG/openMVG/blob/develop/docs/sphinx/rst/software/SfM/SfM.rst#notes-about-spherical-sfm

Here as an example the pipeline to use in order to process equirectangular images (360 images) for SfM.
"""

import glob
import os
import shutil
from pathlib import Path
from typing import List, Tuple

import argoverse.utils.subprocess_utils as subprocess_utils
import gtsfm.utils.io as io_utils
import numpy as np
from gtsam import Rot3, Pose3

from salve.baselines.sfm_reconstruction import SfmReconstruction
from salve.common.posegraph2d import REDTEXT, ENDCOLOR
from salve.dataset.zind_partition import DATASET_SPLITS
from salve.utils.function_timeout import timeout


OPENMVG_SFM_BIN = "/Users/johnlam/Downloads/openMVG_Build/Darwin-x86_64-RELEASE"

# OPENMVG_DEMO_ROOT = "/Users/johnlam/Downloads/openmvg_demo_NOSEEDPAIR_UPRIGHTMATCHING"
OPENMVG_DEMO_ROOT = "/Users/johnlam/Downloads/openmvg_demo_NOSEEDPAIR_UPRIGHTMATCHING__UPRIGHT_ESSENTIAL_ANGULAR"


def panoid_from_key(key: str) -> int:
    """Extract panorama id from panorama image file name.

    Given 'floor_01_partial_room_01_pano_11.jpg', return 11
    """
    return int(Path(key).stem.split("_")[-1])


def load_openmvg_reconstructions_from_json(json_fpath: str, building_id: str, floor_id: str) -> List[SfmReconstruction]:
    """Read OpenMVG-specific format ("sfm_data.json") to AutoFloorPlan generic types.

    Args:
        building_id: unique ID for ZinD building.
        floor_id: unique ID for floor of a ZinD building.
        reconstruction_fpath: path to reconstruction/sfm_data.json file

    Returns:
        reconstructions
    """
    data = io_utils.read_json_file(json_fpath)

    assert data["sfm_data_version"] == "0.3"

    intrinsics = data["intrinsics"] # noqa
    #print("OpenMVG Estimated Instrinsics: ", intrinsics)
    view_metadata = data["views"] # noqa
    #print("OpenMVG Estimated View Metadata: ", view_metadata)
    extrinsics = data["extrinsics"]

    key_to_fname_dict = {}
    for view in data["views"]:
        openmvg_key = view["key"]
        filename = view["value"]["ptr_wrapper"]["data"]["filename"]
        key_to_fname_dict[openmvg_key] = filename

    pose_dict = {}

    for ext_info in extrinsics:
        openmvg_key = ext_info["key"]
        R = np.array(ext_info["value"]["rotation"])
        # See https://github.com/openMVG/openMVG/issues/671
        # and http://openmvg.readthedocs.io/en/latest/openMVG/cameras/cameras/#pinhole-camera-model
        t = -R @ np.array(ext_info["value"]["center"])

        cTw = Pose3(Rot3(R), t)
        wTc = cTw.inverse()

        filename = key_to_fname_dict[openmvg_key]

        pano_id = panoid_from_key(filename)
        pose_dict[pano_id] = wTc

    reconstruction = SfmReconstruction(
        camera=None,  # could provide spherical properties
        pose_dict=pose_dict,
        points=np.zeros((0, 3)),
        rgb=np.zeros((0, 3)).astype(np.uint8),
    )

    # OpenSfM only returns the largest connected component for incremental
    # (See Pierre Moulon's comment here: https://github.com/openMVG/openMVG/issues/1938)
    return [reconstruction]


def find_seed_pair(image_dirpath: str) -> Tuple[str, str]:
    """Choose a seed pair for incremental SfM by finding any two images that are next to
    each other in trajectory/capture order.

    TODO: try with 3 different seed pairs, and choose the best among all.
    """
    image_fpaths = glob.glob(f"{image_dirpath}/*.jpg")

    # choose a seed pair
    # sort by temporal order (last key)
    image_fpaths.sort(key=lambda x: int(Path(x).stem.split("_")[-1]))

    # find an adjacent pair
    frame_idxs = np.array([int(Path(x).stem.split("_")[-1]) for x in image_fpaths])
    temporal_dist = np.diff(frame_idxs)

    # this, and the next pair, are useful
    valid_seed_idxs = np.where(np.absolute(temporal_dist) == 1)[0]

    seed_idx_1 = valid_seed_idxs[0]
    seed_idx_2 = seed_idx_1 + 1

    seed_fname1 = Path(image_fpaths[seed_idx_1]).name
    seed_fname2 = Path(image_fpaths[seed_idx_2]).name
    return seed_fname1, seed_fname2


def run_openmvg_commands_single_tour(image_dirpath: str, matches_dirpath: str, reconstruction_dirpath: str) -> None:
    """Run OpenMVG over a single floor of a single building, by sequentially executing binaries for each SfM stage.

    The reconstruction result / estimated global poses will be written to a file named "sfm_data.json".

    Args:
        image_dirpath: path to temp. directory containing all images to use for reconstruction of a single floor.
        matches_dirpath: path to directory where matches info will be stored.
        reconstruction_dirpath: path to directory where reconstruction info will be stored.
    """
    #seed_fname1, seed_fname2 = find_seed_pair(image_dirpath)

    use_spherical_angular = False
    use_spherical_angular_upright = True

    # Configure the scene to use the Spherical camera model and a unit focal length
    # "-c" is "camera_model" and "-f" is "focal_pixels"
    # defined here: https://github.com/openMVG/openMVG/blob/develop/src/openMVG/cameras/Camera_Common.hpp#L48
    cmd = f"{OPENMVG_SFM_BIN}/openMVG_main_SfMInit_ImageListing -i {image_dirpath} -o {matches_dirpath} -c 7 -f 1"
    stdout, stderr = subprocess_utils.run_command(cmd, return_output=True)
    print("STDOUT: ", stdout)
    print("STDERR: ", stderr)

    # Extract the features (using the HIGH preset is advised, since the spherical image introduced distortions)
    # Can also pass "-u 1" for upright, per:
    #     https://github.com/openMVG/openMVG/blob/develop/docs/sphinx/rst/software/SfM/ComputeFeatures.rst
    cmd = f"{OPENMVG_SFM_BIN}/openMVG_main_ComputeFeatures -i {matches_dirpath}/sfm_data.json -o {matches_dirpath} -m SIFT -p HIGH -u 1"
    stdout, stderr = subprocess_utils.run_command(cmd, return_output=True)
    print("STDOUT: ", stdout)
    print("STDERR: ", stderr)

    # Computes the matches (using the Essential matrix with an angular constraint)
    # can also pass the "-u" for upright, per https://github.com/openMVG/openMVG/issues/1731
    # "a: essential matrix with an angular parametrization,\n"
    # See https://github.com/openMVG/openMVG/blob/develop/src/software/SfM/main_ComputeMatches.cpp#L118
    # "u: upright essential matrix.\n"
    # GeometricFilter_ESphericalMatrix_AC_Angular
    # https://github.com/openMVG/openMVG/blob/develop/src/software/SfM/main_ComputeMatches.cpp#L496
    # ESSENTIAL_MATRIX_ANGULAR -> GeometricFilter_ESphericalMatrix_AC_Angular<false>
    # ESSENTIAL_MATRIX_UPRIGHT -> GeometricFilter_ESphericalMatrix_AC_Angular<true>
    # https://github.com/openMVG/openMVG/blob/develop/src/openMVG/matching_image_collection/E_ACRobust_Angular.hpp
    cmd = f"{OPENMVG_SFM_BIN}/openMVG_main_ComputeMatches -i {matches_dirpath}/sfm_data.json -o {matches_dirpath}"
    if use_spherical_angular:
        cmd += " -g a"
    elif use_spherical_angular_upright:
        cmd += " -g u"

    stdout, stderr = subprocess_utils.run_command(cmd, return_output=True)
    print("STDOUT: ", stdout)
    print("STDERR: ", stderr)

    # Compute the reconstruction
    cmd = f"{OPENMVG_SFM_BIN}/openMVG_main_IncrementalSfM -i {matches_dirpath}/sfm_data.json"
    cmd += f" -m {matches_dirpath} -o {reconstruction_dirpath}" #" -a {seed_fname1} -b {seed_fname2}"
    # Since the spherical geometry is different than classic pinhole images, the best is to provide the initial pair
    # by hand with the -a -b image basenames (i.e. R0010762.JPG).

    try:
        with timeout(seconds=60*5):
            stdout, stderr = subprocess_utils.run_command(cmd, return_output=True)
            print("STDOUT: ", stdout)
            print("STDERR: ", stderr)
    except TimeoutError:
        print("Execution timed out, OpenMVG is stuck")
        return

    # if execution successful, convert result from binary file to JSON
    input_fpath = f"{reconstruction_dirpath}/sfm_data.bin"
    output_fpath = f"{reconstruction_dirpath}/sfm_data.json"
    # convert the "VIEWS", "INTRINSICS", "EXTRINSICS" with -V -I -E
    cmd = f"{OPENMVG_SFM_BIN}/openMVG_main_ConvertSfM_DataFormat -i {input_fpath} -o {output_fpath} -V -I -E"
    subprocess_utils.run_command(cmd)


def run_openmvg_all_tours() -> None:
    """Run OpenMVG in spherical geometry mode, over all tours inside ZinD."""

    raw_dataset_dir = "/Users/johnlam/Downloads/zind_bridgeapi_2021_10_05"

    building_ids = [Path(dirpath).stem for dirpath in glob.glob(f"{raw_dataset_dir}/*")]
    building_ids.sort()

    for building_id in building_ids:

         # we are only evaluating OpenMVG on ZInD's test split.
        if building_id not in DATASET_SPLITS["test"]:
            continue

        floor_ids = ["floor_00", "floor_01", "floor_02", "floor_03", "floor_04", "floor_05"]

        try:
            building_id_cast = int(building_id)
        except:
            print(f"Invalid building id {building_id}, skipping...")
            continue

        for floor_id in floor_ids:
            print(f"Running OpenMVG on {building_id}, {floor_id}")

            FLOOR_OPENMVG_DATADIR = f"{OPENMVG_DEMO_ROOT}/ZinD_{building_id}_{floor_id}__2021_12_02"

            matches_dirpath = f"{FLOOR_OPENMVG_DATADIR}/matches"
            reconstruction_json_fpath = f"{FLOOR_OPENMVG_DATADIR}/reconstruction/sfm_data.json"
            if Path(reconstruction_json_fpath).exists() or Path(matches_dirpath).exists():
                print(f"\tResults already exists for Building {building_id}, {floor_id}, skipping...")
                continue

            src_pano_dir = f"{raw_dataset_dir}/{building_id}/panos"
            pano_fpaths = glob.glob(f"{src_pano_dir}/{floor_id}_*.jpg")

            if len(pano_fpaths) == 0:
                print(REDTEXT + f"\tFloor {floor_id} does not exist for building {building_id}, skipping" + ENDCOLOR)
                continue
            
            os.makedirs(f"{FLOOR_OPENMVG_DATADIR}/images", exist_ok=True)

            # make a copy of all of the panos
            dst_dir = f"{FLOOR_OPENMVG_DATADIR}/images"
            for pano_fpath in pano_fpaths:
                fname = Path(pano_fpath).name
                dst_fpath = f"{dst_dir}/{fname}"
                shutil.copyfile(src=pano_fpath, dst=dst_fpath)

            matches_dirpath = f"{FLOOR_OPENMVG_DATADIR}/matches"
            reconstruction_dirpath = f"{FLOOR_OPENMVG_DATADIR}/reconstruction"

            run_openmvg_commands_single_tour(
                image_dirpath=dst_dir,  # [full path image directory]
                matches_dirpath=matches_dirpath,  # [matches directory]
                reconstruction_dirpath=reconstruction_dirpath,  # [reconstruction directory]
            )
            # delete copy of all of the copies of the panos
            shutil.rmtree(dst_dir)


if __name__ == "__main__":
    run_openmvg_all_tours()
