import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import matplotlib.pyplot as plt
import numpy as np
import open3d as o3d
from argoverse.utils.se2 import SE2
from argoverse.utils.sim2 import Sim2
from imageio import imread

# from vis_zind_annotations import rotmat2d

from afp.common.pano_data import WDO
from afp.common.posegraph2d import PoseGraph2d
from afp.utils.zorder_utils import choose_elevated_repeated_vals
from afp.utils.interpolation_utils import remove_hallucinated_content, interp_dense_grid_from_sparse
from afp.utils.rotation_utils import rotmat2d
from afp.utils.pano_utils import get_uni_sphere_xyz
from afp.utils.colormap import colormap


def prune_to_2d_bbox(
    pts: np.ndarray, rgb: np.ndarray, xmin: float, ymin: float, xmax: float, ymax: float
) -> np.ndarray:
    """"""
    x = pts[:, 0]
    y = pts[:, 1]
    is_valid = np.logical_and.reduce([xmin <= x, x <= xmax, ymin <= y, y <= ymax])
    return pts[is_valid], rgb[is_valid]


def test_prune_to_2d_bbox():
    """ """
    pts = np.array([[-2, 2], [2, 0], [1, 2], [0, 1]])  # will be discarded  # will be discarded
    xmin = -1
    ymin = -1
    xmax = 1
    ymax = 2

    pts = prune_to_2d_bbox(pts, xmin, ymin, xmax, ymax)
    gt_pts = np.array([[1, 2], [0, 1]])
    assert np.allclose(pts, gt_pts)


class BEVParams:
    def __init__(
        self, img_h: int = 2000, img_w: int = 2000, meters_per_px: float = 0.005, accumulate_sweeps: bool = True
    ) -> None:
        """meters_per_px is resolution

        1000 pixels * (0.005 m / px) = 5 meters in each direction
        """
        self.img_h = img_h
        self.img_w = img_w
        self.meters_per_px = meters_per_px
        self.accumulate_sweeps = accumulate_sweeps

        # num px in horizontal direction
        h_px = img_w / 2

        # num px in vertical direction
        v_px = img_h / 2

        # get grid boundaries in meters
        xmin_m = -int(h_px * meters_per_px)
        xmax_m = int(h_px * meters_per_px)
        ymin_m = -int(v_px * meters_per_px)
        ymax_m = int(v_px * meters_per_px)

        xlims = [xmin_m, xmax_m]
        ylims = [ymin_m, ymax_m]

        self.xlims = xlims
        self.ylims = ylims


def rasterize_room_layout_pair(
    i2Ti1: Sim2, gt_floor_pose_graph: PoseGraph2d, building_id: str, floor_id: str, i1: int, i2: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Args:
        i2Ti1:
        gt_floor_pose_graph:
        building_id:
        floor_id:
        i1:
        i2:

    Returns:
        img1
        img2
    """
    bev_params = BEVParams()

    i1_room_vertices = gt_floor_pose_graph.nodes[i1].room_vertices_local_2d
    i2_room_vertices = gt_floor_pose_graph.nodes[i2].room_vertices_local_2d

    # repeat first vertex as last vertex, so OpenCV polygon rendering will close the boundary.
    i1_room_vertices = np.vstack([i1_room_vertices, i1_room_vertices[0].reshape(-1, 2)])
    i2_room_vertices = np.vstack([i2_room_vertices, i2_room_vertices[0].reshape(-1, 2)])

    i1_room_vertices = i2Ti1.transform_from(i1_room_vertices)

    # plt.plot(i1_room_vertices[:,0], i1_room_vertices[:,1], 10, color='r')
    # plt.plot(i2_room_vertices[:,0], i2_room_vertices[:,1], 10, color='b')

    i1_wdos = (
        gt_floor_pose_graph.nodes[i1].doors
        + gt_floor_pose_graph.nodes[i1].windows
        + gt_floor_pose_graph.nodes[i1].openings
    )
    i1_wdos = [i1_wdo.transform_from(i2Ti1) for i1_wdo in i1_wdos]
    img1 = rasterize_single_layout(bev_params, i1_room_vertices, wdo_objs=i1_wdos)

    i2_wdos = (
        gt_floor_pose_graph.nodes[i2].doors
        + gt_floor_pose_graph.nodes[i2].windows
        + gt_floor_pose_graph.nodes[i2].openings
    )
    # i2_wdos are already in frame i2, so they do not need to be transformed.
    img2 = rasterize_single_layout(bev_params, i2_room_vertices, wdo_objs=i2_wdos)
    # plt.axis("equal")
    # plt.show()
    # quit()

    return img1, img2


def rasterize_single_layout(bev_params: BEVParams, room_vertices: np.ndarray, wdo_objs: List[WDO]) -> np.ndarray:
    """Render single room layout, with room boundary in white, and windows, doors, and openings marked in unique colors.
    TODO: render as mask, or as polyline

    Args:
        bev_params:
        room_vertices:
        wdo_objs:

    Returns:
        bev_img:
    """
    HOHO_S_ZIND_SCALE_FACTOR = 1.5

    grid_xmin, grid_xmax = bev_params.xlims
    grid_ymin, grid_ymax = bev_params.ylims
    bevimg_Sim2_world = Sim2(R=np.eye(2), t=np.array([-grid_xmin, -grid_ymin]), s=1 / bev_params.meters_per_px)

    img_h = bev_params.img_h + 1
    img_w = bev_params.img_w + 1

    bev_img = np.zeros((img_h, img_w, 3), dtype=np.uint8)

    WHITE = (255, 255, 255)
    bev_img = rasterize_polyline(
        polyline_xy=room_vertices * HOHO_S_ZIND_SCALE_FACTOR,
        bev_img=bev_img,
        bevimg_Sim2_world=bevimg_Sim2_world,
        color=WHITE,
        thickness=10,
    )

    RED = [255, 0, 0]
    GREEN = [0, 255, 0]
    BLUE = [0, 0, 255]
    wdo_color_dict_cv2 = {"windows": RED, "doors": GREEN, "openings": BLUE}

    for wdo_idx, wdo in enumerate(wdo_objs):

        wdo_type = wdo.type
        wdo_color = wdo_color_dict_cv2[wdo_type]
        bev_img = rasterize_polyline(
            polyline_xy=wdo.vertices_local_2d * HOHO_S_ZIND_SCALE_FACTOR,
            bev_img=bev_img,
            bevimg_Sim2_world=bevimg_Sim2_world,
            color=wdo_color,
            thickness=10,
        )
    bev_img = np.flipud(bev_img)
    return bev_img


def rasterize_polyline(
    polyline_xy: np.ndarray, bev_img: np.ndarray, bevimg_Sim2_world: Sim2, color: Tuple[int, int, int], thickness: int
) -> np.ndarray:
    """
    Args:
        polyline_xy
        bev_img
        bevimg_Sim2_world
        color
        thickness

    Returns:
        bev_img
    """
    img_h, img_w, _ = bev_img.shape

    img_xy = bevimg_Sim2_world.transform_from(polyline_xy)
    img_xy = np.round(img_xy).astype(np.int64)

    draw_polyline_cv2(line_segments_arr=img_xy, image=bev_img, color=color, im_h=img_h, im_w=img_w, thickness=thickness)
    return bev_img


def draw_polyline_cv2(
    line_segments_arr: np.ndarray,
    image: np.ndarray,
    color: Tuple[int, int, int],
    im_h: int,
    im_w: int,
    thickness: int = 2,
) -> None:
    """Draw a polyline onto an image using given line segments.

    Based on https://github.com/argoai/argoverse-api/blob/master/argoverse/utils/cv2_plotting_utils.py#L86

    Args:
        line_segments_arr: Array of shape (K, 2) representing the coordinates of each line segment
        image: Array of shape (M, N, 3), representing a 3-channel BGR image
        color: Tuple of shape (3,) with a BGR format color
        im_h: Image height in pixels
        im_w: Image width in pixels
    """
    for i in range(line_segments_arr.shape[0] - 1):
        x1 = line_segments_arr[i][0]
        y1 = line_segments_arr[i][1]
        x2 = line_segments_arr[i + 1][0]
        y2 = line_segments_arr[i + 1][1]

        #x_in_range = (x1 >= 0) and (x2 >= 0) and (y1 >= 0) and (y2 >= 0)
        #y_in_range = (x1 < im_w) and (x2 < im_w) and (y1 < im_h) and (y2 < im_h)

        #if x_in_range and y_in_range:
        # Use anti-aliasing (AA) for curves
        image = cv2.line(image, (x1, y1), (x2, y2), color, thickness=thickness, lineType=cv2.LINE_AA)


def render_bev_image(bev_params: BEVParams, xyzrgb: np.ndarray, is_semantics: bool) -> Optional[np.ndarray]:
    """
    Args:
        bev_params: parameters for rendering
        xyzrgb: should be inside the world coordinate frame
        is_semantics

    Returns:
        bev_img
    """
    xyz = xyzrgb[:, :3]
    rgb = xyzrgb[:, 3:] * 255

    # in meters
    grid_xmin, grid_xmax = bev_params.xlims
    grid_ymin, grid_ymax = bev_params.ylims

    # in meters
    xyz, rgb = prune_to_2d_bbox(xyz, rgb, grid_xmin, grid_ymin, grid_xmax, grid_ymax)

    num_pts = xyz.shape[0]
    print(f"Rendering {num_pts/1e6} million points")

    if num_pts == 0:
        return None

    # # m/px -> px/m, then px/m * #meters = #pixels
    bevimg_Sim2_world = Sim2(R=np.eye(2), t=np.array([-grid_xmin, -grid_ymin]), s=1 / bev_params.meters_per_px)

    xy = xyz[:, :2]
    z = xyz[:, 2]
    img_xy = bevimg_Sim2_world.transform_from(xy)
    img_xy = np.round(img_xy).astype(np.int64)
    # xmax, ymax = np.amax(img_xy, axis=0)
    # img_h = ymax + 1
    # img_w = xmax + 1

    # import pdb; pdb.set_trace()
    img_h = bev_params.img_h + 1
    img_w = bev_params.img_w + 1

    x = img_xy[:, 0]
    y = img_xy[:, 1]

    prioritize_elevated = True
    if prioritize_elevated:
        # import pdb; pdb.set_trace()
        valid = choose_elevated_repeated_vals(x, y, z)
        img_xy = img_xy[valid]
        rgb = rgb[valid]

        x = x[valid]
        y = y[valid]

    sparse_bev_img = np.zeros((img_h, img_w, 3), dtype=np.uint8)
    sparse_bev_img[y, x] = rgb

    interp_bev_img = np.zeros((img_h, img_w, 3), dtype=np.uint8)

    # now, apply interpolation to it
    interp_bev_img = interp_dense_grid_from_sparse(
        interp_bev_img, img_xy, rgb, grid_h=img_h, grid_w=img_w, is_semantics=is_semantics
    )

    # apply filter to it, to remove hallicuniated parts in all black regions
    bev_img = remove_hallucinated_content(sparse_bev_img, interp_bev_img)
    bev_img = np.flipud(bev_img)

    visualize = False
    if visualize:
        import matplotlib.pyplot as plt

        plt.imshow(bev_img)
        plt.show()

    return bev_img


def grayscale_to_color(gray_img: np.ndarray) -> np.ndarray:
    """Duplicate the grayscale channel 3 times.

    Args:
    gray_img: Array with shape (M,N)

    Returns:
    rgb_img: Array with shape (M,N,3)
    """
    h, w = gray_img.shape
    rgb_img = np.zeros((h, w, 3), dtype=np.uint8)
    for i in range(3):
        rgb_img[:, :, i] = gray_img
    return rgb_img


CEILING_CLASS_IDX = 36
MIRROR_CLASS_IDX = 85
WALL_CLASS_IDX = 191


def get_xyzrgb_from_depth(args, depth_fpath: str, rgb_fpath: str, is_semantics: bool) -> np.ndarray:
    """
    Args:
        xyzrgb, with rgb in [0,1] as floats
    """
    depth = imread(depth_fpath)[..., None].astype(np.float32) * args.scale

    # Reading rgb-d
    rgb = imread(rgb_fpath)

    width = 1024
    height = 512
    rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_NEAREST if is_semantics else cv2.INTER_LINEAR)

    if is_semantics:
        # remove ceiling and mirror points
        invalid = np.logical_or(rgb == CEILING_CLASS_IDX, rgb == MIRROR_CLASS_IDX)
        depth[invalid] = np.nan

        rgb_colormap = colormap()
        num_colors = rgb_colormap.shape[0]
        rgb = rgb_colormap[rgb % num_colors]
    else:

        if rgb.ndim == 2:
            rgb = grayscale_to_color(rgb)

    # Project to 3d
    H, W = rgb.shape[:2]
    xyz = depth * get_uni_sphere_xyz(H, W)

    xyzrgb = np.concatenate([xyz, rgb / 255.0], 2)

    # Crop the image and flatten
    if args.crop_ratio > 0:
        assert args.crop_ratio < 1
        crop = int(H * args.crop_ratio)
        # remove the bottom rows of pano, and remove the top rows of pano
        xyzrgb = xyzrgb[crop:-crop]

    xyzrgb = xyzrgb.reshape(-1, 6)

    # Crop in 3d
    # fmt: off
    within_crop_range = np.logical_and(
        xyzrgb[:, 2] > args.crop_z_range[0],
        xyzrgb[:, 2] <= args.crop_z_range[1]
    )
    # fmt: on
    xyzrgb = xyzrgb[within_crop_range]

    return xyzrgb


def vis_depth_and_render(args, is_semantics: bool):
    """ """
    xyzrgb = get_xyzrgb_from_depth(args, depth_fpath=args.depth, rgb_fpath=args.img, is_semantics=is_semantics)

    # Visualize
    visualize = True
    if visualize:

        invalid = np.isnan(xyzrgb[:, 0])
        xyzrgb = xyzrgb[~invalid]

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(xyzrgb[:, :3])
        pcd.colors = o3d.utility.Vector3dVector(xyzrgb[:, 3:])

        o3d.visualization.draw_geometries(
            geometry_list=[
                pcd,
                o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.3, origin=[0, 0, 0]),
            ],
            window_name=Path(args.img).stem,
        )

    bev_params = BEVParams()
    bev_img = render_bev_image(bev_params, xyzrgb, is_semantics)
    return bev_img


def vis_depth(args):
    """ """
    # Reading rgb-d
    rgb = imread(args.img)
    depth = imread(args.depth)[..., None].astype(np.float32) * args.scale

    width = 1024
    height = 512
    rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LINEAR)

    # Project to 3d
    H, W = rgb.shape[:2]
    xyz = depth * get_uni_sphere_xyz(H, W)
    xyzrgb = np.concatenate([xyz, rgb / 255.0], 2)

    # Crop the image and flatten
    if args.crop_ratio > 0:
        assert args.crop_ratio < 1
        crop = int(H * args.crop_ratio)
        # remove the bottom rows of pano, and remove the top rows of pano
        xyzrgb = xyzrgb[crop:-crop]

    xyzrgb = xyzrgb.reshape(-1, 6)

    # Crop in 3d
    xyzrgb = xyzrgb[xyzrgb[:, 2] <= args.crop_z_above]

    # Visualize
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(xyzrgb[:, :3])
    pcd.colors = o3d.utility.Vector3dVector(xyzrgb[:, 3:])

    o3d.visualization.draw_geometries(
        [pcd, o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.3, origin=[0, 0, 0])]
    )


def render_bev_pair(
    args, building_id: str, floor_id: str, i1: int, i2: int, i2Ti1: Sim2, is_semantics: bool
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """ """

    xyzrgb1 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i1, rgb_fpath=args.img_i1, is_semantics=is_semantics)
    xyzrgb2 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i2, rgb_fpath=args.img_i2, is_semantics=is_semantics)

    # floor_map_json['scale_meters_per_coordinate']
    scale_meters_per_coordinate = 3.7066488344243465
    print(i2Ti1)

    # HoHoNet center of pano is to -x, but in ZinD center of pano is +y
    R = rotmat2d(-90)

    xyzrgb1[:, :2] = xyzrgb1[:, :2] @ R.T
    xyzrgb2[:, :2] = xyzrgb2[:, :2] @ R.T

    HOHO_S_ZIND_SCALE_FACTOR = 1.5

    xyzrgb1[:, :2] = (xyzrgb1[:, :2] @ i2Ti1.rotation.T) + (
        i2Ti1.translation * HOHO_S_ZIND_SCALE_FACTOR
    )  # * scale_meters_per_coordinate # * np.array([-1,1]))
    # xyzrgb1[:,:2] = i2Ti1.transform_from(xyzrgb1[:,:2]) #

    bev_params = BEVParams()
    img1 = render_bev_image(bev_params, xyzrgb1, is_semantics=is_semantics)
    img2 = render_bev_image(bev_params, xyzrgb2, is_semantics=is_semantics)

    if img1 is None or img2 is None:
        return None, None

    visualize = False
    if visualize:
        # plt.scatter(xyzrgb1[:,0], xyzrgb1[:,1], 10, color='r', marker='.', alpha=0.1)
        plt.scatter(xyzrgb1[:, 0], xyzrgb1[:, 1], 10, c=xyzrgb1[:, 3:], marker=".", alpha=0.1)
        # plt.axis("equal")
        # plt.show()

        # plt.scatter(xyzrgb2[:,0], xyzrgb2[:,1], 10, color='b', marker='.', alpha=0.1)
        plt.scatter(xyzrgb2[:, 0], xyzrgb2[:, 1], 10, c=xyzrgb2[:, 3:], marker=".", alpha=0.1)

        plt.title("")
        plt.axis("equal")
        plt.show()
        # save_fpath = f"aligned_examples_2021_07_12/gt_aligned_approx/{building_id}/{floor_id}/{i1}_{i2}.jpg"
        # os.makedirs(Path(save_fpath).parent, exist_ok=True)
        # plt.savefig(save_fpath, dpi=1000)
        # plt.close("all")

        # 30,35 on floor2 bug

    return img1, img2


def get_bev_pair_xyzrgb(
    args, building_id: str, floor_id: str, i1: int, i2: int, i2Ti1: Sim2, is_semantics: bool
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """ """

    xyzrgb1 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i1, rgb_fpath=args.img_i1, is_semantics=is_semantics)
    xyzrgb2 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i2, rgb_fpath=args.img_i2, is_semantics=is_semantics)

    # floor_map_json['scale_meters_per_coordinate']
    scale_meters_per_coordinate = 3.7066488344243465
    print(i2Ti1)

    # HoHoNet center of pano is to -x, but in ZinD center of pano is +y
    R = rotmat2d(-90)

    xyzrgb1[:, :2] = xyzrgb1[:, :2] @ R.T
    xyzrgb2[:, :2] = xyzrgb2[:, :2] @ R.T

    HOHO_S_ZIND_SCALE_FACTOR = 1.5

    xyzrgb1[:, :2] = (xyzrgb1[:, :2] @ i2Ti1.rotation.T) + (
        i2Ti1.translation * HOHO_S_ZIND_SCALE_FACTOR
    )  # * scale_meters_per_coordinate # * np.array([-1,1]))
    # xyzrgb1[:,:2] = i2Ti1.transform_from(xyzrgb1[:,:2]) #

    return xyzrgb1, xyzrgb2


if __name__ == "__main__":

    # import argparse
    # parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    # parser.add_argument('--img', required=True,
    #                     help='Image texture in equirectangular format')
    # parser.add_argument('--depth', required=True,
    #                     help='Depth map')
    # parser.add_argument('--scale', default=0.001, type=float,
    #                     help='Rescale the depth map')
    # parser.add_argument('--crop_ratio', default=80/512, type=float,
    #                     help='Crop ratio for upper and lower part of the image')
    # parser.add_argument('--crop_z_above', default=1.2, type=float,
    #                     help='Filter 3D point with z coordinate above')
    # args = parser.parse_args()

    # test_find_duplicates_1()
    # test_find_duplicates_2()
    # test_find_duplicates_3()
    pass
