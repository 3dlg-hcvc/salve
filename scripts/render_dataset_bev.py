"""
Render aligned texture maps and/or layouts in a bird's eye view, to be used for training a network.
"""

import glob
import os
from multiprocessing import Pool
from pathlib import Path
from types import SimpleNamespace
from typing import List

import argoverse.utils.json_utils as json_utils
import cv2
import imageio
import numpy as np
from argoverse.utils.sim2 import Sim2

import afp.common.posegraph2d as posegraph2d
import afp.dataset.hnet_prediction_loader as hnet_prediction_loader
import afp.utils.bev_rendering_utils as bev_rendering_utils
import afp.utils.hohonet_inference as hohonet_inference_utils
from afp.common.posegraph2d import PoseGraph2d
from afp.dataset.zind_partition import DATASET_SPLITS

"""
Nasty depth map estimation failure cases: (from complete_07_10 version)
    # (building, pano_ids)
    "000": [10],  # pano 10 outside
    "004": [10, 24, 28, 56, 58],  # building 004, pano 10 and pano 24, pano 28,56,58 (outdoors)
    "006": [10],
    "981": [5, 7, 14, 11, 16, 17, 28],  # 11 is a bit inaccurate
"""


def panoid_from_fpath(fpath: str) -> int:
    """Derive panorama's id from its filename."""
    return int(Path(fpath).stem.split("_")[-1])


def resize_image(image: np.ndarray, h: int, w: int) -> np.ndarray:
    """
    Args:
        image: array of shape (H,W,3)
        h: desired height of output image, in pixels.
        w: desired width of output image, in pixels.

    Returns:
        image: array pf shape (h,w,3)
    """
    image = cv2.resize(image, (w, h), interpolation=cv2.INTER_LINEAR)
    return image


def render_building_floor_pairs(
    depth_save_root: str,
    bev_save_root: str,
    hypotheses_save_root: str,
    raw_dataset_dir: str,
    building_id: str,
    floor_id: str,
    layout_save_root: str,
    render_modalities: List[str]
) -> None:
    """Render BEV texture maps for a single floor of a single ZinD building.

    Given a set of possible alignment hypotheses for the floor, render all possible BEV floor-ceiling image pairs.

    Args:
        depth_save_root: directory where depth maps should be saved (or are already cached here).
        bev_save_root: directory where bird's eye view texture maps should be saved.
        hypotheses_save_root: directory where putative alignment hypotheses are saved.
        raw_dataset_dir: path to ZinD dataset.
        building_id: unique ID of ZinD building.
        floor_id: unique ID of floor.
        layout_save_root:
        render_modalities: either "rgb_texture" or "layout", or both
    """
    if "layout" in render_modalities:
        # load the layouts, either inferred or GT.
        use_inferred_wdos_layout = True
        if use_inferred_wdos_layout:
            floor_pose_graphs = hnet_prediction_loader.load_inferred_floor_pose_graphs(
                query_building_id=building_id, raw_dataset_dir=raw_dataset_dir
            )
            if floor_pose_graphs is None:
                return
            floor_pose_graph = floor_pose_graphs[floor_id]
        else:
            floor_pose_graph = posegraph2d.get_gt_pose_graph(building_id, floor_id, raw_dataset_dir)

    img_fpaths = glob.glob(f"{raw_dataset_dir}/{building_id}/panos/*.jpg")
    img_fpaths_dict = {panoid_from_fpath(fpath): fpath for fpath in img_fpaths}

    floor_labels_dirpath = f"{hypotheses_save_root}/{building_id}/{floor_id}"

    for label_type in ["gt_alignment_approx", "incorrect_alignment"]:  # "gt_alignment_exact"
        pairs = glob.glob(f"{floor_labels_dirpath}/{label_type}/*.json")
        pairs.sort()
        print(f"On Building {building_id}, {floor_id}, {label_type}")

        for pair_idx, pair_fpath in enumerate(pairs):

            for surface_type in ["floor", "ceiling"]:
                is_semantics = False
                # if is_semantics:
                #     crop_z_range = [-float('inf'), 2.0]
                # else:

                if surface_type == "floor":
                    # everything 1 meter and below the camera
                    crop_z_range = [-float("inf"), -1.0]

                elif surface_type == "ceiling":
                    # everything 50 cm and above camera
                    crop_z_range = [0.5, float("inf")]

                i2Ti1 = Sim2.from_json(json_fpath=pair_fpath)

                i1, i2 = Path(pair_fpath).stem.split("_")[:2]
                i1, i2 = int(i1), int(i2)

                # e.g. 'door_0_0_identity'
                pair_uuid = Path(pair_fpath).stem.split("__")[-1]

                img1_fpath = img_fpaths_dict[i1]
                img2_fpath = img_fpaths_dict[i2]

                building_bev_save_dir = f"{bev_save_root}/{label_type}/{building_id}"
                os.makedirs(building_bev_save_dir, exist_ok=True)

                def bev_fname_from_img_fpath(pair_idx: int, pair_uuid: str, surface_type: str, img_fpath: str) -> None:
                    """ """
                    fname_stem = Path(img_fpath).stem
                    if is_semantics:
                        img_name = f"pair_{pair_idx}___{pair_uuid}_{surface_type}_semantics_{fname_stem}.jpg"
                    else:
                        img_name = f"pair_{pair_idx}___{pair_uuid}_{surface_type}_rgb_{fname_stem}.jpg"
                    return img_name

                bev_fname1 = bev_fname_from_img_fpath(pair_idx, pair_uuid, surface_type, img1_fpath)
                bev_fname2 = bev_fname_from_img_fpath(pair_idx, pair_uuid, surface_type, img2_fpath)

                bev_fpath1 = f"{building_bev_save_dir}/{bev_fname1}"
                bev_fpath2 = f"{building_bev_save_dir}/{bev_fname2}"

                if "rgb_texture" in render_modalities:
                    print(f"On {i1},{i2}")
                    hohonet_inference_utils.infer_depth_if_nonexistent(
                        depth_save_root=depth_save_root, building_id=building_id, img_fpath=img1_fpath
                    )
                    hohonet_inference_utils.infer_depth_if_nonexistent(
                        depth_save_root=depth_save_root, building_id=building_id, img_fpath=img2_fpath
                    )
                    args = SimpleNamespace(
                        **{
                            "img_i1": semantic_img1_fpath if is_semantics else img1_fpath,
                            "img_i2": semantic_img2_fpath if is_semantics else img2_fpath,
                            "depth_i1": f"{depth_save_root}/{building_id}/{Path(img1_fpath).stem}.depth.png",
                            "depth_i2": f"{depth_save_root}/{building_id}/{Path(img2_fpath).stem}.depth.png",
                            "scale": 0.001,
                            # throw away top 80 and bottom 80 rows of pixel (too noisy of estimates)
                            "crop_ratio": 80 / 512,
                            "crop_z_range": crop_z_range,  # 0.3 # -1.0 # -0.5 # 0.3 # 1.2
                        }
                    )
                    # bev_img = bev_rendering_utils.vis_depth_and_render(args, is_semantics=False)

                    if Path(bev_fpath1).exists() and Path(bev_fpath2).exists():
                        print("Both BEV images already exist, skipping...")
                        continue

                    bev_img1, bev_img2 = bev_rendering_utils.render_bev_pair(
                        args, building_id, floor_id, i1, i2, i2Ti1, is_semantics=False
                    )

                    if bev_img1 is None or bev_img2 is None:
                        continue

                    # bev_img1 = resize_image(bev_img1, h=500, w=500)
                    # bev_img2 = resize_image(bev_img2, h=500, w=500)

                    imageio.imwrite(bev_fpath1, bev_img1)
                    imageio.imwrite(bev_fpath2, bev_img2)

                if "layout" not in render_modalities:
                    continue
                if surface_type == "floor":

                    building_layout_save_dir = f"{layout_save_root}/{label_type}/{building_id}"
                    os.makedirs(building_layout_save_dir, exist_ok=True)

                    # change to layout dir
                    layout_fpath1 = f"{building_layout_save_dir}/{bev_fname1}"
                    layout_fpath2 = f"{building_layout_save_dir}/{bev_fname2}"

                    if Path(layout_fpath1).exists() and Path(layout_fpath2).exists():
                        print("Both layout images already exist, skipping...")
                        continue

                    # skip for ceiling, since would be duplicate.
                    layoutimg1, layoutimg2 = bev_rendering_utils.rasterize_room_layout_pair(
                        i2Ti1=i2Ti1,
                        floor_pose_graph=floor_pose_graph,
                        building_id=building_id,
                        floor_id=floor_id,
                        i1=i1,
                        i2=i2,
                    )
                    imageio.imwrite(layout_fpath1, layoutimg1)
                    imageio.imwrite(layout_fpath2, layoutimg2)


def render_pairs(
    num_processes: int,
    depth_save_root: str,
    bev_save_root: str,
    raw_dataset_dir: str,
    hypotheses_save_root: str,
    layout_save_root: str,
    render_modalities: List[str],
) -> None:
    """Render BEV texture maps for all floors of all ZinD buildings.

    Args:
        num_processes: number of processes to use for parallel rendering.
        depth_save_root: directory where depth maps should be saved (or are already cached here).
        bev_save_root: directory where bird's eye view texture maps should be saved.
        raw_dataset_dir: path to ZinD dataset.
        hypotheses_save_root: directory where putative alignment hypotheses are saved.
        layout_save_root:
        render_modalities:
    """

    # discover possible building ids and floors
    building_ids = [Path(fpath).stem for fpath in glob.glob(f"{raw_dataset_dir}/*") if Path(fpath).is_dir()]
    building_ids.sort()

    args = []

    for building_id in building_ids:

        # for rendering test data only
        if building_id not in DATASET_SPLITS["test"]:
            continue

        json_annot_fpath = f"{raw_dataset_dir}/{building_id}/zind_data.json"
        if not Path(json_annot_fpath).exists():
            print(f"zind_data.json file missing for {building_id}")

        floor_map_json = json_utils.read_json_file(json_annot_fpath)

        if "merger" not in floor_map_json:
            print(f"No merger data in {building_id}: {json_annot_fpath}")
            continue

        merger_data = floor_map_json["merger"]
        for floor_id in merger_data.keys():
            args += [
                (
                    depth_save_root,
                    bev_save_root,
                    hypotheses_save_root,
                    raw_dataset_dir,
                    building_id,
                    floor_id,
                    layout_save_root,
                    render_modalities,
                )
            ]

    if num_processes > 1:
        with Pool(num_processes) as p:
            p.starmap(render_building_floor_pairs, args)
    else:
        for single_call_args in args:
            render_building_floor_pairs(*single_call_args)


if __name__ == "__main__":
    """ """

    num_processes = 15

    # depth_save_root = "/Users/johnlam/Downloads/HoHoNet_Depth_Maps"
    # depth_save_root = "/mnt/data/johnlam/HoHoNet_Depth_Maps"

    # depth_save_root = "/Users/johnlam/Downloads/ZinD_Bridge_API_HoHoNet_Depth_Maps"
    # depth_save_root = "/mnt/data/johnlam/ZinD_Bridge_API_HoHoNet_Depth_Maps"
    depth_save_root = "/home/johnlam/ZinD_Bridge_API_HoHoNet_Depth_Maps"

    # hypotheses_save_root = "/Users/johnlam/Downloads/jlambert-auto-floorplan/verifier_dataset_2021_06_21"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_alignment_hypotheses_2021_06_25"
    # hypotheses_save_root = "/mnt/data/johnlam/ZinD_alignment_hypotheses_2021_06_25"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_alignment_hypotheses_2021_07_07"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_alignment_hypotheses_2021_07_14_w_wdo_idxs"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_alignment_hypotheses_2021_07_14_v2_w_wdo_idxs"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_alignment_hypotheses_2021_07_14_v3_w_wdo_idxs"
    # hypotheses_save_root = "/mnt/data/johnlam/ZinD_alignment_hypotheses_2021_07_14_v3_w_wdo_idxs"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_07_11_alignment_hypotheses_2021_08_04_Sim3"
    # hypotheses_save_root = "/mnt/data/johnlam/ZinD_07_11_alignment_hypotheses_2021_08_04_Sim3"
    # hypotheses_save_root = "/Users/johnlam/Downloads/ZinD_bridge_api_alignment_hypotheses_madori_rmx_v1_2021_10_16_SE2"
    # hypotheses_save_root = "/mnt/data/johnlam/ZinD_bridge_api_alignment_hypotheses_madori_rmx_v1_2021_10_16_SE2"
    # hypotheses_save_root = "/mnt/data/johnlam/ZinD_bridge_api_alignment_hypotheses_madori_rmx_v1_2021_10_17_SE2"
    # hypotheses_save_root = "/home/johnlam/ZinD_bridge_api_alignment_hypotheses_madori_rmx_v1_2021_10_17_SE2"
    
    # w/ inferred WDO and inferred layout
    # hypotheses_save_root = (
    #     "/home/johnlam/ZinD_bridge_api_alignment_hypotheses_madori_rmx_v1_2021_10_20_SE2_width_thresh0.65"
    # )

    # w/ GT WDO + GT layout
    hypotheses_save_root = "/home/johnlam/ZinD_bridge_api_alignment_hypotheses_GT_WDO_2021_11_20_SE2_width_thresh0.8"


    # raw_dataset_dir = "/Users/johnlam/Downloads/2021_05_28_Will_amazon_raw"
    # raw_dataset_dir = "/Users/johnlam/Downloads/ZInD_release/complete_zind_paper_final_localized_json_6_3_21"
    # raw_dataset_dir = "/mnt/data/johnlam/ZInD_release/complete_zind_paper_final_localized_json_6_3_21"
    # raw_dataset_dir = DO NOT USE "/mnt/data/zhiqiangw/ZInD_final_07_11/complete_07_10_new"
    # raw_dataset_dir = "/mnt/data/johnlam/complete_07_10_new"
    # raw_dataset_dir = "/Users/johnlam/Downloads/complete_07_10_new"

    # raw_dataset_dir = "/Users/johnlam/Downloads/zind_bridgeapi_2021_10_05"
    # raw_dataset_dir = "/mnt/data/johnlam/zind_bridgeapi_2021_10_05"
    raw_dataset_dir = "/home/johnlam/zind_bridgeapi_2021_10_05"

    # bev_save_root = "/Users/johnlam/Downloads/ZinD_BEV_2021_06_24"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_BEV_RGB_only_2021_06_25"
    # bev_save_root = "/mnt/data/johnlam/ZinD_BEV_RGB_only_2021_06_25"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_BEV_RGB_only_2021_07_14_v2"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_BEV_RGB_only_2021_07_14_v3"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_BEV_RGB_only_2021_08_03_layoutimgs_filledpoly"
    # bev_save_root = "/mnt/data/johnlam/ZinD_07_11_BEV_RGB_only_2021_08_04_ZinD"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_07_11_BEV_RGB_only_2021_08_04_ZinD"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_Bridge_API_BEV_2021_10_16"
    # bev_save_root = "/mnt/data/johnlam/ZinD_Bridge_API_BEV_2021_10_16"
    # bev_save_root = "/mnt/data/johnlam/ZinD_Bridge_API_BEV_2021_10_17"
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_Bridge_API_BEV_2021_10_20_res500x500"
    # bev_save_root = "/home/johnlam/ZinD_Bridge_API_BEV_2021_10_20_lowres"  # BEST
    # bev_save_root = "/Users/johnlam/Downloads/ZinD_Bridge_API_BEV_2021_10_23_debug"

    # from GT WDO and GT layout
    bev_save_root = "/home/johnlam/Renderings_ZinD_bridge_api_GT_WDO_2021_11_20_SE2_width_thresh0.8"

    # layout_save_root = "/Users/johnlam/Downloads/ZinD_BEV_RGB_only_2021_08_03_layoutimgs"
    # layout_save_root = "/mnt/data/johnlam/ZinD_07_11_BEV_RGB_only_2021_08_04_layoutimgs"
    # layout_save_root = "/Users/johnlam/Downloads/ZinD_07_11_BEV_RGB_only_2021_08_04_layoutimgs"
    layout_save_root = None
    # layout_save_root = "/home/johnlam/ZinD_Bridge_API_BEV_2021_10_20_lowres_layoutimgs_inferredlayout"

    render_modalities = ["rgb_texture"] # ["layout"]

    render_pairs(
        num_processes=num_processes,
        depth_save_root=depth_save_root,
        bev_save_root=bev_save_root,
        raw_dataset_dir=raw_dataset_dir,
        hypotheses_save_root=hypotheses_save_root,
        layout_save_root=layout_save_root,
        render_modalities=render_modalities
    )