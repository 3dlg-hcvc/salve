"""
"""

import glob
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from argoverse.utils.json_utils import read_json_file

from afp.common.posegraph2d import get_gt_pose_graph
from afp.utils.pr_utils import assign_tp_fp_fn_tn


@dataclass(frozen=False)
class EdgeClassification:
    """Represents a model prediction for a particular alignment hypothesis between Panorama i1 and Panorama i2.

    Note: i1 and i2 are panorama id's
    """

    i1: int
    i2: int
    prob: float
    y_hat: int
    y_true: int
    pair_idx: int
    wdo_pair_uuid: str
    configuration: str


def get_edge_classifications_from_serialized_preds(
    serialized_preds_json_dir: str,
) -> Dict[Tuple[str, str], List[EdgeClassification]]:
    """

    Args:
        serialized_preds_json_dir:

    Returns:
        floor_edgeclassifications_dict
    """
    floor_edgeclassifications_dict = defaultdict(list)

    json_fpaths = glob.glob(f"{serialized_preds_json_dir}/batch*.json")
    for json_fpath in json_fpaths:

        json_data = read_json_file(json_fpath)
        y_hat_list = json_data["y_hat"]
        y_true_list = json_data["y_true"]
        y_hat_prob_list = json_data["y_hat_probs"]
        fp0_list = json_data["fp0"]
        fp1_list = json_data["fp1"]

        for y_hat, y_true, y_hat_prob, fp0, fp1 in zip(y_hat_list, y_true_list, y_hat_prob_list, fp0_list, fp1_list):
            i1 = int(Path(fp0).stem.split("_")[-1])
            i2 = int(Path(fp1).stem.split("_")[-1])
            building_id = Path(fp0).parent.stem

            s = Path(fp0).stem.find("floor_")
            e = Path(fp0).stem.find("_partial")
            floor_id = Path(fp0).stem[s:e]

            pair_idx = Path(fp0).stem.split("_")[1]

            is_identity = "identity" in Path(fp0).stem
            configuration = "identity" if is_identity else "rotated"

            k = Path(fp0).stem.split("___")[1].find(f"_{configuration}")
            assert k != -1

            wdo_pair_uuid = Path(fp0).stem.split("___")[1][:k]
            assert any([wdo_type in wdo_pair_uuid for wdo_type in ["door", "window", "opening"]])

            floor_edgeclassifications_dict[(building_id, floor_id)] += [
                EdgeClassification(
                    i1=i1,
                    i2=i2,
                    prob=y_hat_prob,
                    y_hat=y_hat,
                    y_true=y_true,
                    pair_idx=pair_idx,
                    wdo_pair_uuid=wdo_pair_uuid,
                    configuration=configuration,
                )
            ]
    return floor_edgeclassifications_dict


def vis_edge_classifications(serialized_preds_json_dir: str, raw_dataset_dir: str) -> None:
    """ """
    floor_edgeclassifications_dict = get_edge_classifications_from_serialized_preds(serialized_preds_json_dir)

    color_dict = {"TP": "green", "FP": "red", "FN": "orange", "TN": "blue"}

    # loop over each building and floor
    for (building_id, floor_id), measurements in floor_edgeclassifications_dict.items():

        # if building_id != '1490': # '1394':# '1635':
        # 	continue

        print(f"On building {building_id}, {floor_id}")
        gt_floor_pose_graph = get_gt_pose_graph(building_id, floor_id, raw_dataset_dir)

        # gather all of the edge classifications
        y_hat = np.array([m.y_hat for m in measurements])
        y_true = np.array([m.y_true for m in measurements])

        # classify into TPs, FPs, FNs, TNs
        is_TP, is_FP, is_FN, is_TN = assign_tp_fp_fn_tn(y_true, y_pred=y_hat)
        for m, is_tp, is_fp, is_fn, is_tn in zip(measurements, is_TP, is_FP, is_FN, is_TN):

            # then render the edges
            if is_tp:
                color = color_dict["TP"]
                # gt_floor_pose_graph.draw_edge(m.i1, m.i2, color)
                print(f"\tFP: ({m.i1},{m.i2}) for pair {m.pair_idx}")

            elif is_fp:
                color = color_dict["FP"]

            elif is_fn:
                color = color_dict["FN"]
                # gt_floor_pose_graph.draw_edge(m.i1, m.i2, color)

            elif is_tn:
                color = color_dict["TN"]
                gt_floor_pose_graph.draw_edge(m.i1, m.i2, color)

            # if m.i1 or m.i2 not in gt_floor_pose_graph.nodes:
            # 	import pdb; pdb.set_trace()

        # import pdb; pdb.set_trace()
        # render the pose graph first
        gt_floor_pose_graph.render_estimated_layout()
        # continue


if __name__ == "__main__":
    """ """
    # serialized_preds_json_dir = "/Users/johnlam/Downloads/2021_07_13_binary_model_edge_classifications"
    # serialized_preds_json_dir = "/Users/johnlam/Downloads/2021_07_13_edge_classifications_fixed_argmax_bug/2021_07_13_edge_classifications_fixed_argmax_bug"
    serialized_preds_json_dir = "/Users/johnlam/Downloads/ZinD_trained_models_2021_06_25/2021_06_28_07_01_26/2021_07_15_serialized_edge_classifications/2021_07_15_serialized_edge_classifications"

    raw_dataset_dir = "/Users/johnlam/Downloads/ZInD_release/complete_zind_paper_final_localized_json_6_3_21"
    # raw_dataset_dir = "/Users/johnlam/Downloads/2021_05_28_Will_amazon_raw"
    vis_edge_classifications(serialized_preds_json_dir, raw_dataset_dir)




