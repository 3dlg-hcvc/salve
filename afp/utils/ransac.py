"""RANSAC based Sim(3) pose alignment."""

import copy
import math
from typing import List, Optional, Tuple

import numpy as np
import gtsfm.utils.geometry_comparisons as gtsfm_geometry_comparisons
from gtsam import Rot3, Pose3, Similarity3


DEFAULT_DELETE_FRAC = 0.33


def ransac_align_poses_sim3_ignore_missing(
    aTi_list_ref: List[Optional[Pose3]],
    bTi_list_est: List[Optional[Pose3]],
    num_iters=1000,
    delete_frac=DEFAULT_DELETE_FRAC,
) -> Tuple[List[Optional[Pose3]], Similarity3]:
    """
    Account for outliers in the pose graph.

    Args:
        num_iters: number of RANSAC iterations to execture.
        delete_frac: what percent of data to remove when fitting a single hypothesis.
    """
    best_aligned_bTi_list_est = None
    best_aSb = None
    best_trans_error = float("inf")
    best_rot_error = float("inf")

    valid_idxs = [i for i, bTi in enumerate(bTi_list_est) if bTi is not None]
    num_to_delete = math.ceil(delete_frac * len(valid_idxs))
    if len(valid_idxs) - num_to_delete <= 3:
        # run without RANSAC! want at least 3 frame pairs for good alignment.
        aligned_bTi_list_est, aSb = gtsfm_geometry_comparisons.align_poses_sim3_ignore_missing(
            aTi_list_ref, bTi_list_est
        )
        return aligned_bTi_list_est, aSb

    # randomly delete some elements
    for _ in range(num_iters):

        aTi_list_ref_subset = copy.deepcopy(aTi_list_ref)
        bTi_list_est_subset = copy.deepcopy(bTi_list_est)

        # randomly delete 33% of the poses
        delete_idxs = np.random.choice(a=valid_idxs, size=num_to_delete, replace=False)
        for del_idx in delete_idxs:
            bTi_list_est_subset[del_idx] = None

        aligned_bTi_list_est, aSb = gtsfm_geometry_comparisons.align_poses_sim3_ignore_missing(
            aTi_list_ref_subset, bTi_list_est_subset
        )

        # evaluate inliers.
        rot_error, trans_error = compute_pose_errors_3d(aTi_list_ref, aligned_bTi_list_est)
        # print("Deleted ", delete_idxs, f" -> trans_error {trans_error:.1f}, rot_error {rot_error:.1f}")

        if trans_error <= best_trans_error and rot_error <= best_rot_error:
            # print(f"Found better trans error {trans_error:.2f} < {best_trans_error:.2f}")
            # print(f"Found better rot error {rot_error:.2f} < {best_rot_error:.2f}")
            best_aligned_bTi_list_est = aligned_bTi_list_est
            best_aSb = aSb
            best_trans_error = trans_error
            best_rot_error = rot_error

    return best_aligned_bTi_list_est, best_aSb


def compute_pose_errors_3d(
    aTi_list_gt: List[Pose3], aligned_bTi_list_est: List[Optional[Pose3]]
) -> Tuple[float, float]:
    """Compute average pose errors over all cameras (separately in rotation and translation).

    Note: pose graphs must already be aligned.

    Args:
        aTi_list_gt: ground truth 2d pose graph.
        aligned_bTi_list_est:

    Returns:
        mean_rot_err: mean rotation error per camera, in degrees.
        mean_trans_err: mean translation error per camera.
    """
    # print("aTi_list_gt: ", aTi_list_gt)
    # print("aligned_bTi_list_est",  aligned_bTi_list_est)

    rotation_errors = []
    translation_errors = []
    for (aTi, aTi_) in zip(aTi_list_gt, aligned_bTi_list_est):
        if aTi is None or aTi_ is None:
            continue
        rot_err = gtsfm_geometry_comparisons.compute_relative_rotation_angle(aTi.rotation(), aTi_.rotation())
        trans_err = np.linalg.norm(aTi.translation() - aTi_.translation())

        rotation_errors.append(rot_err)
        translation_errors.append(trans_err)

    # print("Rotation Errors: ", np.round(rotation_errors,1))
    # print("Translation Errors: ", np.round(translation_errors,1))
    mean_rot_err = np.mean(rotation_errors)
    mean_trans_err = np.mean(translation_errors)
    return mean_rot_err, mean_trans_err


def test_ransac_align_poses_sim3_ignore_missing() -> None:
    """ """

    # write unit test for simple case of 3 poses (one is an outlier with massive translation error.)

    aTi_list = [
        None,
        Pose3(Rot3(), np.array([50, 0, 0])),
        Pose3(Rot3(), np.array([0, 10, 0])),
        Pose3(Rot3(), np.array([0, 0, 20])),
        None,
    ]

    # below was previously in b's frame.
    aTi_list_ = [
        None,
        Pose3(Rot3(), np.array([50.1, 0, 0])),
        Pose3(Rot3(), np.array([0, 9.9, 0])),
        Pose3(Rot3(), np.array([0, 0, 2000])),
        None,
    ]

    aligned_bTi_list_est, aSb = ransac_align_poses_sim3_ignore_missing(aTi_list, aTi_list_)

    assert np.isclose(aSb.scale(), 1.0, atol=1e-2)
    assert np.allclose(aligned_bTi_list_est[1].translation(), np.array([50.0114, 0.0576299, 0]), atol=1e-3)
    assert np.allclose(aligned_bTi_list_est[2].translation(), np.array([-0.0113879, 9.94237, 0]), atol=1e-3)