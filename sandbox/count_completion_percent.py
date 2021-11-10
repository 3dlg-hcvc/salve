"""Count what percent of data from a particular split has been rendered.
"""

import glob
from pathlib import Path

from afp.dataset.zind_partition import DATASET_SPLITS


EPS = 1e-10


def main() -> None:
    """ """
    desired_split = "test"

    hypotheses_save_root = (
        "/home/johnlam/ZinD_bridge_api_alignment_hypotheses_madori_rmx_v1_2021_10_20_SE2_width_thresh0.65"
    )
    bev_save_root = "/home/johnlam/ZinD_Bridge_API_BEV_2021_10_20_lowres"

    building_ids = [Path(d).name for d in glob.glob(f"{bev_save_root}/gt_alignment_approx/*")]

    split_building_ids = DATASET_SPLITS[desired_split]
    for building_id in sorted(building_ids):

        if building_id not in split_building_ids:
            continue

        rendering_percent_dict = {}
        for label_type in ["gt_alignment_approx", "incorrect_alignment"]:

            # find the floors
            label_hypotheses_dirpath = f"{hypotheses_save_root}/{building_id}/*/{label_type}"
            expected_num_label = len(glob.glob(f"{label_hypotheses_dirpath}/*"))

            label_render_dirpath = f"{bev_save_root}/{label_type}/{building_id}"
            num_rendered_label = len(glob.glob(f"{label_render_dirpath}/*")) / 4
            
            label_rendering_percent = num_rendered_label / (expected_num_label + EPS) * 100  # matches

            rendering_percent_dict[label_type] = label_rendering_percent

        pos_rendering_percent = rendering_percent_dict["gt_alignment_approx"]
        neg_rendering_percent = rendering_percent_dict["incorrect_alignment"]
        print(f"Building {building_id} Pos. {pos_rendering_percent:.2f}% Neg. {neg_rendering_percent:.2f}%")


if __name__ == "__main__":

    main()
