"""Script to execute floorplan stitching using localized panos and estimated layouts."""

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from tqdm import tqdm
from matplotlib.figure import Figure

import salve.stitching.draw as draw_utils
import salve.stitching.ground_truth_utils as ground_truth_utils
import salve.stitching.shape as shape_utils
import salve.stitching.transform as transform_utils
from salve.stitching.loaders import MemoryLoader
from salve.stitching.models.floor_map_object import FloorMapObject
from salve.stitching.models.locations import Point2d, Pose


def main(output_dir: str, path_localization: str, dir_predictions: str, path_floor_map: str) -> None:
    """TODO

    Args:
        output_dir: TODO
        path_localization: TODO
        dir_predictions: TODO
        path_floor_map: TODO
    """

    print(f"Start processing ... ")

    loader = MemoryLoader(dir_predictions, data_type={"rse": ["partial_v1"], "dwo": ["rcnn"]})

    if not Path(output_dir).exists():
        Path(output_dir).mkdir(exist_ok=True, parents=True)
    cluster_dir = os.path.join(output_dir, "fused")
    if not Path(cluster_dir).exists():
        Path(cluster_dir).mkdir(exist_ok=True, parents=True)

    # Load floor_map file with annotated room shape and gt room shape transformations.
    with open(path_floor_map) as f:
        floor_map = json.load(f)

    with open(path_localization) as f:
        localizations = json.load(f)

    # clusters = []
    # for i_cluster, cluster in enumerate(localizations['global_clusters']):
    #     clusters.append({})
    #     clusters[i_cluster] = {
    #         key: val for key, val in cluster['panos'].items()
    #     }

    predicted_shapes_all = []
    location_panos_all = []
    dwos_cluster_all = []
    wall_confidences_all = []
    shapes_by_floor = []

    floor_map_object = FloorMapObject(floor_map)

    dwos_gt_all = {}
    for rsid in floor_map["room_shapes"]:
        try:
            room_global = floor_map_object.get_room_shape_global(rsid)
        except Exception:
            continue
        this_all = []
        for type in ["doors", "windows", "openings"]:
            for wfid, obj in room_global[type].items():
                this_all.append(
                    [
                        Point2d(obj["position"][0]["x"], obj["position"][0]["y"]),
                        Point2d(obj["position"][1]["x"], obj["position"][1]["y"]),
                        type[:-1],
                    ]
                )
        dwos_gt_all[rsid] = this_all

    clusters = []
    floor_ids = []
    for item in localizations:
        cluster_new = ground_truth_utils.align_pred_poses_with_gt(floor_map_object=floor_map_object, cluster=item)
        clusters.append(cluster_new["panos"])
        floor_ids.append(cluster_new["floor_id"])
    # clusters = ground_truth_utils.convert_floor_map_to_localization_cluster(floor_map_object)

    all_scores = []
    for i_cluster, cluster in enumerate(clusters):
        print(f"Start process on cluster {i_cluster} ... ")
        cluster_name = f"cluster_{i_cluster}"
        cluster_dir = os.path.join(output_dir, "fused", cluster_name)
        if not Path(cluster_dir).exists():
            Path(cluster_dir).mkdir(exist_ok=True, parents=True)

        predicted_shapes = {}
        predicted_shapes_raw = {}
        dwos_cluster = {}
        location_panos = {}
        wall_confidences = {}
        filename = f"cluster_{i_cluster}.png"
        filename_raw = f"cluster_raw_{i_cluster}.png"
        vis_path = os.path.join(output_dir, filename)
        vis_raw_path = os.path.join(output_dir, filename_raw)

        print(f"Loading cluster {len(cluster)} panos ... ")
        primary_panoids = []
        for i_pano, panoid in enumerate(cluster):
            path_madori_prediction = f"{dir_predictions}/{panoid}/rmx-madori-v1_predictions.json"
            with open(path_madori_prediction) as f:
                pred = json.load(f)

            rsid = floor_map["panos"][panoid]["room_shape_id"]
            pano_room_shape = floor_map["room_shapes"][rsid]["panos"][panoid]
            is_primary = (
                pano_room_shape["position"]["x"] == 0
                and pano_room_shape["position"]["y"] == 0
                and pano_room_shape["rotation"] == 0
            )
            if is_primary:
                primary_panoids.append(panoid)

            if len(pred[0]["predictions"]["room_shape"]["corners_in_uv"]) < 3:
                continue
            wall_confidences[panoid] = pred[0]["predictions"]["room_shape"]["raw_predictions"][
                "floor_boundary_uncertainty"
            ]
            predicted_shapes_raw[panoid], wall_confidences[panoid] = shape_utils.generate_dense_shape(
                v_vals=pred[0]["predictions"]["room_shape"]["raw_predictions"]["floor_boundary"],
                uncertainty=wall_confidences[panoid],
            )
            predicted_shapes[panoid] = shape_utils.load_room_shape_polygon_from_predictions(
                room_shape_pred=pred[0]["predictions"]["room_shape"]["corners_in_uv"]
            )

            pose_raw = cluster[panoid]["pose"]
            pose = Pose(position=Point2d(x=pose_raw["x"], y=pose_raw["y"]), rotation=pose_raw["rotation"])
            location_panos[panoid] = pose
            # dwos = []
            # for type in ['window', 'door', 'opening']:
            #     for dwo_uv_pred in pred[0]['predictions']['wall_features'][type]:
            #         xys = transform_utils.ray_cast_and_generate_dwo_xy(dwo_uv_pred, predicted_shapes[panoid])
            #         if not xys[0] or not xys[1]:
            #             continue
            #         dwos.append([
            #             transform_utils.transform_xy_by_pose(xys[0], pose),
            #             transform_utils.transform_xy_by_pose(xys[1], pose),
            #             type
            #         ])
            # dwos_cluster[panoid] = dwos

        predicted_shapes_all.append(predicted_shapes)
        location_panos_all.append(location_panos)
        # dwos_cluster_all.append(dwos_cluster)
        wall_confidences_all.append(wall_confidences)

        groups = shape_utils.group_panos_by_room(predicted_shapes, location_panos)

        print("Running shape refinement ... ")
        floor_shape_final, figure, floor_shape_fused_poly = shape_utils.refine_predicted_shape(
            groups=groups,
            predicted_shapes=predicted_shapes_raw,
            wall_confidences=wall_confidences,
            location_panos=location_panos,
            cluster_dir=cluster_dir,
            tour_dir=output_dir,
        )
        shapes_by_floor.append(floor_shape_final)

        print("Drawing room shapes ... ")
        # gt_axis = figure.add_subplot(1, 3, 2)
        # poly_gt_union = draw_utils.draw_all_room_shapes_with_poses(None, floor_map, primary_panoids, axis=gt_axis)
        # for panoid in cluster:
        #     if panoid in primary_panoids:
        #         continue
        #     pose_ref = floor_map_object.get_pano_global_pose(panoid)
        #     draw_utils.draw_camera_in_top_down_canvas(gt_axis, pose_ref, "green", size=10)
        #
        # area_gt = poly_gt_union.area
        # area_pred = floor_shape_fused_poly.area
        # area_union = poly_gt_union.union(floor_shape_fused_poly).area
        # area_intersection = poly_gt_union.intersection(floor_shape_fused_poly).area
        # iou = area_intersection / area_union
        # all_scores.append({
        #     "i_cluster": i_cluster,
        #     "iou": iou,
        #     "area_gt": area_gt,
        #     "area_pred": area_pred,
        #     "area_union": area_union,
        #     "area_intersection": area_intersection
        # })

        # for panoid in cluster:
        #     if panoid in primary_panoids:
        #         continue
        #     pose_ref = floor_map_object.get_pano_global_pose(panoid)
        #     draw_utils.draw_camera_in_top_down_canvas(gt_axis, pose_ref, "black", size=10)

        gt_axis1 = figure.add_subplot(1, 2, 2)
        floor_id = floor_ids[i_cluster]
        fsid = None
        for fsid_this, floor_shape in floor_map["floor_shapes"].items():
            if floor_shape["floor_number"] == int(floor_id.split("_")[-1]):
                fsid = fsid_this

        panoids_all = []
        primary_panoids_all = []
        if fsid:
            panoids_all = floor_map_object.get_panoids_with_floor_id(fsid)
            for panoid_this in panoids_all:
                rsid = floor_map["panos"][panoid_this]["room_shape_id"]
                pano_room_shape = floor_map["room_shapes"][rsid]["panos"][panoid_this]
                is_primary = (
                    pano_room_shape["position"]["x"] == 0
                    and pano_room_shape["position"]["y"] == 0
                    and pano_room_shape["rotation"] == 0
                )
                if is_primary:
                    primary_panoids_all.append(panoid_this)

        poly_gt_union1 = draw_utils.draw_all_room_shapes_with_poses(None, floor_map, primary_panoids_all, axis=gt_axis1)
        rsids = [floor_map["panos"][this_panoid]["room_shape_id"] for this_panoid in primary_panoids_all]
        dwos_gt_this = {}
        for rsid in rsids:
            dwos_gt_this[rsid] = dwos_gt_all[rsid]
        draw_utils.draw_dwo_xy_top_down_canvas(gt_axis1, figure, "", dwos_gt_this)
        for panoid in panoids_all:
            if panoid in primary_panoids_all:
                continue
            pose_ref = floor_map_object.get_pano_global_pose(panoid)
            draw_utils.draw_camera_in_top_down_canvas(gt_axis1, pose_ref, "black", size=10)

        area_gt1 = poly_gt_union1.area
        area_pred1 = floor_shape_fused_poly.area
        area_union1 = poly_gt_union1.union(floor_shape_fused_poly).area
        area_intersection1 = poly_gt_union1.intersection(floor_shape_fused_poly).area
        iou1 = area_intersection1 / area_union1
        # all_scores.append({
        #     "i_cluster": i_cluster,
        #     "iou": iou,
        #     "area_gt": area_gt,
        #     "area_pred": area_pred,
        #     "area_union": area_union,
        #     "area_intersection": area_intersection,
        #     "iou_all": iou1,
        #     "area_gt_all": area_gt1,
        #     "area_pred_all": area_pred1,
        #     "area_union_all": area_union1,
        #     "area_intersection_all": area_intersection1
        # })

        xlim_min = min(figure.axes[0].get_xlim()[0], figure.axes[1].get_xlim()[0])
        xlim_max = max(figure.axes[0].get_xlim()[1], figure.axes[1].get_xlim()[1])
        ylim_min = min(figure.axes[0].get_ylim()[0], figure.axes[1].get_ylim()[0])
        ylim_max = max(figure.axes[0].get_ylim()[1], figure.axes[1].get_ylim()[1])
        # xlim_min = min(figure.axes[0].get_xlim()[0], figure.axes[2].get_xlim()[0])
        # xlim_max = max(figure.axes[0].get_xlim()[1], figure.axes[2].get_xlim()[1])
        # ylim_min = min(figure.axes[0].get_ylim()[0], figure.axes[2].get_ylim()[0])
        # ylim_max = max(figure.axes[0].get_ylim()[1], figure.axes[2].get_ylim()[1])
        figure.axes[0].set_xlim([xlim_min, xlim_max])
        figure.axes[0].set_ylim([ylim_min, ylim_max])
        figure.axes[1].set_xlim([xlim_min, xlim_max])
        figure.axes[1].set_ylim([ylim_min, ylim_max])
        # figure.axes[2].set_xlim([xlim_min, xlim_max])
        # figure.axes[2].set_ylim([ylim_min, ylim_max])
        figure.tight_layout(pad=0.1)
        # plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.1)
        # figure.savefig(os.path.join(cluster_dir, 'final.png'), dpi = 300)
        figure.savefig(os.path.join(cluster_dir, "final.jpg"), dpi=600)
        # figure.subplots_adjust(bottom=0.1, top=0.1)
        # figure.savefig(os.path.join(cluster_dir, 'final.png'), dpi = 300)

        axis, fig = draw_utils.draw_all_room_shapes_with_given_poses_and_shapes(
            filename=vis_path,
            floor_map=floor_map,
            panoid_refs=predicted_shapes.keys(),
            predictions=predicted_shapes,
            confidences=wall_confidences,
            poses=location_panos,
            groups=groups,
        )
        # draw_utils.draw_dwo_xy_top_down_canvas(axis, fig, vis_path, dwos_cluster)
        axis, fig = draw_utils.draw_all_room_shapes_with_given_poses_and_shapes(
            filename=vis_raw_path,
            floor_map=floor_map,
            panoid_refs=predicted_shapes.keys(),
            predictions=predicted_shapes_raw,
            confidences=wall_confidences,
            poses=location_panos,
            groups=groups,
        )
        # draw_utils.draw_dwo_xy_top_down_canvas(axis, fig, vis_raw_path, dwos_cluster)

    with open(os.path.join(output_dir, "score.json"), "w") as f:
        json.dump(all_scores, f)
    # total_group = 0
    # for cluster in shapes_by_floor:
    #     total_group += len(cluster)
    # fig_floor = Figure()
    # axis_floor = fig_floor.add_subplot(1, 1, 1)
    # i_group = 0
    #
    # for cluster in shapes_by_floor:
    #     for group in cluster:
    #         color = hsv2rgb(i_group / total_group, 1, 1)
    #         i_group += 1
    #         color = (color[0]/255, color[1]/255, color[2]/255)
    #         for [xys_fused, conf_fused, pose0] in group:
    #             draw_utils.draw_shape_in_top_down_canvas_fill(axis_floor, xys_fused, color, pose=pose0)
    # axis_floor.set_aspect("equal")
    # path_output = os.path.join(output_dir, f'final.png')
    # fig_floor.savefig(path_output, dpi = 300)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Script to localize panorama images on RMX floor maps.")
    parser.add_argument("-o", "--output-dir", type=str, required=True, help="Path to output directory.")
    parser.add_argument(
        "--path-clusters",
        type=str,
        required=True,
        help="Path to panorama cluster json file, generated by SALVe + global optimization.",
    )
    parser.add_argument(
        "--pred-dir", type=str, required=True, help="Directory to per-pano room shape and DWO predictions."
    )
    parser.add_argument("--path-gt", type=str, required=True, help="Path to gt floor_map.json file.")

    args = parser.parse_args()
    output_dir = args.output_dir
    path_localization = args.path_clusters
    dir_predictions = args.pred_dir
    path_floor_map = args.path_gt

    if not Path(path_localization).exists():
        raise FileNotFoundError(f"`path_localization` for {path_localization} not found.")

    if not Path(dir_predictions).exists():
        raise FileNotFoundError(f"`output_dir` for {dir_predictions} not found.")

    if not Path(path_floor_map).exists():
        raise FileNotFoundError(f"`path_floor_map` for {path_floor_map} not found.")

    main(
        output_dir=output_dir,
        path_localization=path_localization,
        dir_predictions=dir_predictions,
        path_floor_map=path_floor_map,
    )
