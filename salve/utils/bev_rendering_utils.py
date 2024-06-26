"""Utilities for rendering bird's eye view texture maps."""

import os
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple, Union

import cv2
import imageio
import matplotlib.pyplot as plt
import numpy as np

import salve.common.bevparams as bevparams
import salve.utils.colormap as colormap_utils
import salve.utils.hohonet_pano_utils as hohonet_pano_utils
import salve.utils.interpolation_utils as interpolation_utils
import salve.utils.rotation_utils as rotation_utils
import salve.utils.zorder_utils as zorder_utils
from salve.common.bevparams import DEFAULT_METERS_PER_PX, BEVParams
from salve.common.pano_data import WDO
from salve.common.posegraph2d import PoseGraph2d
from salve.common.sim2 import Sim2

import salve.utils.hohonet_inference as hohonet_inference_utils


RED = [255, 0, 0]
GREEN = [0, 255, 0]
BLUE = [0, 0, 255]
WDO_COLOR_DICT_CV2 = {"windows": RED, "doors": GREEN, "openings": BLUE}

CEILING_CLASS_IDX = 36
MIRROR_CLASS_IDX = 85
WALL_CLASS_IDX = 191


def prune_to_2d_bbox(
    pts: np.ndarray, rgb: np.ndarray, xmin: float, ymin: float, xmax: float, ymax: float
) -> np.ndarray:
    """Prune 2d point cloud to box with corners [xmin,ymin] and [xmax,ymax], inclusive of boundaries."""
    x = pts[:, 0]
    y = pts[:, 1]
    is_valid = np.logical_and.reduce([xmin <= x, x <= xmax, ymin <= y, y <= ymax])
    return pts[is_valid], rgb[is_valid]


def rasterize_room_layout_pair(
    i2Ti1: Sim2, floor_pose_graph: PoseGraph2d, building_id: str, floor_id: str, i1: int, i2: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Given a pose graph with room layouts and W/D/O locations, rasterize a BEV image of the scene.

    Note: the room layout and W/D/O locations may be inferred, or the ground truth (doesn't matter).
    (Poses from the GT pose graph are not actually used during rasterization).

    Args:
        i2Ti1: relative pose between the two panoramas i1 and i2, such that p_i2 = i2Ti1 * p_i1.
        floor_pose_graph: ground truth or inferred pose graph, containing layout polygons
            and locations of W/D/O objects.
        building_id: unique ID of ZinD building.
        floor_id: unique ID of floor of this ZinD building.
        i1: panorama index for panorama 1.
        i2: panorama index for panorama 2.

    Returns:
        img1: BEV rasterization for panorama i1.
        img2: BEV rasterization for panorama i2.
    """
    bev_params = BEVParams()

    i1_room_vertices = floor_pose_graph.nodes[i1].room_vertices_local_2d
    i2_room_vertices = floor_pose_graph.nodes[i2].room_vertices_local_2d

    # Repeat first vertex as last vertex, so OpenCV polygon rendering will close the boundary.
    i1_room_vertices = np.vstack([i1_room_vertices, i1_room_vertices[0].reshape(-1, 2)])
    i2_room_vertices = np.vstack([i2_room_vertices, i2_room_vertices[0].reshape(-1, 2)])

    i1_room_vertices = i2Ti1.transform_from(i1_room_vertices)

    # plt.plot(i1_room_vertices[:,0], i1_room_vertices[:,1], 10, color='r')
    # plt.plot(i2_room_vertices[:,0], i2_room_vertices[:,1], 10, color='b')

    i1_wdos = (
        floor_pose_graph.nodes[i1].doors + floor_pose_graph.nodes[i1].windows + floor_pose_graph.nodes[i1].openings
    )
    i1_wdos = [i1_wdo.transform_from(i2Ti1) for i1_wdo in i1_wdos]
    img1 = rasterize_single_layout(bev_params, i1_room_vertices, wdo_objs=i1_wdos)

    i2_wdos = (
        floor_pose_graph.nodes[i2].doors + floor_pose_graph.nodes[i2].windows + floor_pose_graph.nodes[i2].openings
    )
    # i2_wdos are already in frame i2, so they do not need to be transformed.
    img2 = rasterize_single_layout(bev_params, i2_room_vertices, wdo_objs=i2_wdos)
    # plt.axis("equal")
    # plt.show()
    # quit()

    return img1, img2


def rasterize_single_layout(
    bev_params: BEVParams, room_vertices: np.ndarray, wdo_objs: List[WDO], render_mask: bool = True
) -> np.ndarray:
    """Render single room layout, with room boundary in white, and windows, doors, and openings marked in unique colors.
    TODO: render as mask, or as polyline

    Args:
        bev_params: hyperparameters for rendering.
        room_vertices: coordinates of single room layout vertices (floor-wall boundary).
        wdo_objs: window, door, and openings detected or annotated from a single room.
        render_mask: whether to render the polygon as a filled mask, or not (otherwise, drawn as a thin contour).

    Returns:
        bev_img: array of shape (H,W,3) representing the rendered/rasterized BEV image.
    """
    HOHO_S_ZIND_SCALE_FACTOR = 1.5
    bevimg_Sim2_world = bev_params.bevimg_Sim2_world

    img_h = bev_params.img_h + 1
    img_w = bev_params.img_w + 1

    bev_img = np.zeros((img_h, img_w, 3), dtype=np.uint8)

    WHITE = (255, 255, 255)

    # Thickness will be 30 px at 2000 x 2000, and just 8 px at 500 x 500
    wdo_thickness_px = bevparams.get_line_width_by_resolution(DEFAULT_METERS_PER_PX)
    if render_mask:
        bev_img = rasterize_polygon(
            polygon_xy=room_vertices * HOHO_S_ZIND_SCALE_FACTOR,
            bev_img=bev_img,
            bevimg_Sim2_world=bevimg_Sim2_world,
            color=WHITE,
        )
    else:
        bev_img = rasterize_polyline(
            polyline_xy=room_vertices * HOHO_S_ZIND_SCALE_FACTOR,
            bev_img=bev_img,
            bevimg_Sim2_world=bevimg_Sim2_world,
            color=WHITE,
            thickness=int(wdo_thickness_px / 3),  # 10 px at 2000 x 2000, and just 2-3 px at 500 x 500
        )

    for wdo_idx, wdo in enumerate(wdo_objs):

        wdo_type = wdo.type
        wdo_color = WDO_COLOR_DICT_CV2[wdo_type]
        bev_img = rasterize_polyline(
            polyline_xy=wdo.vertices_local_2d * HOHO_S_ZIND_SCALE_FACTOR,
            bev_img=bev_img,
            bevimg_Sim2_world=bevimg_Sim2_world,
            color=wdo_color,
            thickness=wdo_thickness_px,
        )
    bev_img = np.flipud(bev_img)
    return bev_img


def draw_polygon_cv2(points: np.ndarray, image: np.ndarray, color: Tuple[int, int, int]) -> np.ndarray:
    """Draw a polygon onto an image using the given points and fill color.
    These polygons are often non-convex, so we cannot use cv2.fillConvexPoly().
    Note that cv2.fillPoly() accepts an array of array of points as an
    argument (i.e. an array of polygons where each polygon is represented
    as an array of points).

    Reference:
    https://github.com/argoai/argoverse-api/blob/master/argoverse/utils/cv2_plotting_utils.py#L116

    Args:
        points: Array of shape (N, 2) representing all points of the polygon
        image: Array of shape (M, N, 3) representing the image to be drawn onto
        color: Tuple of shape (3,) with a BGR format color

    Returns:
        image: Array of shape (M, N, 3) with polygon rendered on it
    """
    points = np.array([points])
    points = points.astype(np.int32)
    image = cv2.fillPoly(image, points, color)  # , lineType[, shift]]) -> None
    return image


def rasterize_polygon(
    polygon_xy: np.ndarray, bev_img: np.ndarray, bevimg_Sim2_world: Sim2, color: Tuple[int, int, int]
) -> np.ndarray:
    """ """
    img_h, img_w, _ = bev_img.shape

    img_xy = bevimg_Sim2_world.transform_from(polygon_xy)
    img_xy = np.round(img_xy).astype(np.int64)

    bev_img = draw_polygon_cv2(points=img_xy, image=bev_img, color=color)
    return bev_img


def rasterize_polyline(
    polyline_xy: np.ndarray, bev_img: np.ndarray, bevimg_Sim2_world: Sim2, color: Tuple[int, int, int], thickness: int
) -> np.ndarray:
    """
    Args:
        polyline_xy: array of shape (N,2) representing polyline coordinates in world coordinates.
        bev_img: array of shape (H,W,3) as image representing bird's eye view.
        bevimg_Sim2_world: transormation that converts world points into bird's eye view image coordinates, e.g.
            p_bevimg = bevimg_Sim2_world * p_world.
        color:
        thickness: line thickness (in pixels).

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
        im_h: Image height in pixels.
        im_w: Image width in pixels.
        thickness: line thickness (in pixels).
    """
    for i in range(line_segments_arr.shape[0] - 1):
        x1 = line_segments_arr[i][0]
        y1 = line_segments_arr[i][1]
        x2 = line_segments_arr[i + 1][0]
        y2 = line_segments_arr[i + 1][1]

        # x_in_range = (x1 >= 0) and (x2 >= 0) and (y1 >= 0) and (y2 >= 0)
        # y_in_range = (x1 < im_w) and (x2 < im_w) and (y1 < im_h) and (y2 < im_h)

        # if x_in_range and y_in_range:
        # Use anti-aliasing (AA) for curves
        image = cv2.line(image, (x1, y1), (x2, y2), color, thickness=thickness, lineType=cv2.LINE_AA)


def render_bev_image(bev_params: BEVParams, xyzrgb: np.ndarray, is_semantics: bool) -> Optional[np.ndarray]:
    """Given a colored point cloud, render it as a 2d texture map. Use sparse to dense interpolation.

    Args:
        bev_params: parameters for rendering
        xyzrgb: array of shape (N,6) representing (x,y,z) coordinates and (r,g,b) values.
           Note: (x,y,z) coordinates should be inside the world coordinate frame
        is_semantics: whether to treat RGB data as semantic data (nearest neighbor interpolation instead of linear)

    Returns:
        bev_img: array of shape (H,W,3) representing a dense texture map
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

    bevimg_Sim2_world = bev_params.bevimg_Sim2_world

    xy = xyz[:, :2]
    z = xyz[:, 2]
    img_xy = bevimg_Sim2_world.transform_from(xy)
    img_xy = np.round(img_xy).astype(np.int64)
    # xmax, ymax = np.amax(img_xy, axis=0)
    # img_h = ymax + 1
    # img_w = xmax + 1

    img_h = bev_params.img_h + 1
    img_w = bev_params.img_w + 1

    x = img_xy[:, 0]
    y = img_xy[:, 1]

    prioritize_elevated = True
    if prioritize_elevated:
        valid = zorder_utils.choose_elevated_repeated_vals(x, y, z)
        img_xy = img_xy[valid]
        rgb = rgb[valid]

        x = x[valid]
        y = y[valid]

    sparse_bev_img = np.zeros((img_h, img_w, 3), dtype=np.uint8)
    sparse_bev_img[y, x] = rgb

    interp_bev_img = np.zeros((img_h, img_w, 3), dtype=np.uint8)

    # Now, apply interpolation to texture map.
    interp_bev_img = interpolation_utils.interp_dense_grid_from_sparse(
        interp_bev_img, img_xy, rgb, grid_h=img_h, grid_w=img_w, is_semantics=is_semantics
    )

    # Apply filter to interpolated texture map, to remove hallucinated parts in all-black regions.
    bev_img = interpolation_utils.remove_hallucinated_content(sparse_bev_img, interp_bev_img)
    bev_img = np.flipud(bev_img)

    visualize = False
    if visualize:
        import matplotlib.pyplot as plt

        plt.imshow(bev_img)
        plt.show()

    return bev_img


def grayscale_to_color(gray_img: np.ndarray) -> np.ndarray:
    """Convert grayscale image to RGB by duplicating the grayscale channel 3 times.

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


def get_xyzrgb_from_depth(
    args: Union[SimpleNamespace, Namespace], depth_fpath: str, rgb_fpath: str, is_semantics: bool
) -> np.ndarray:
    """Obtain colored point cloud by backprojecting panorama image RGB values using a depth map.

    Args:
        args: panorama and backprojected point cloud cropping parameters.
        depth_fpath: file path to depth map.
        rgb_fpath: file path to RGB panorama image.
        is_semantics: whether to interpret image as semantic label map.

    Returns:
        xyzrgb: numpy array of shape (N,6), with rgb in [0,1] as floats.
    """
    if "crop_ratio" not in args.__dict__:
        raise ValueError("Crop ratio for panorama top and bottom must be provided as `args.crop_ratio`.")

    if "crop_z_range" not in args.__dict__:
        raise ValueError("Z-coordinate range for cropping must be provided as `args.crop_z_range`.")

    depth = imageio.imread(depth_fpath)[..., None].astype(np.float32) * args.scale

    # Reading rgb-d
    rgb = imageio.imread(rgb_fpath)

    # Resize panorama from (2048,1024) to (1024, 512).
    width = 1024
    height = 512
    rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_NEAREST if is_semantics else cv2.INTER_LINEAR)

    if is_semantics:
        # Remove ceiling and mirror points.
        invalid = np.logical_or(rgb == CEILING_CLASS_IDX, rgb == MIRROR_CLASS_IDX)
        depth[invalid] = np.nan

        rgb_colormap = colormap_utils.get_tango_colormap()
        num_colors = rgb_colormap.shape[0]
        rgb = rgb_colormap[rgb % num_colors]
    else:

        if rgb.ndim == 2:
            rgb = grayscale_to_color(rgb)

    # Project to 3d.
    H, W = rgb.shape[:2]
    xyz = depth * hohonet_pano_utils.get_uni_sphere_xyz(H, W)

    xyzrgb = np.concatenate([xyz, rgb / 255.0], 2)

    # Crop the image.
    if args.crop_ratio > 0:
        assert args.crop_ratio < 1
        crop = int(H * args.crop_ratio)
        # Remove the bottom rows of pano, and remove the top rows of pano.
        xyzrgb = xyzrgb[crop:-crop]

    # Flatten point cloud from (H,W,6) to (H*W,6).
    xyzrgb = xyzrgb.reshape(-1, 6)

    # Crop point cloud in 3d.
    # fmt: off
    within_crop_range = np.logical_and(
        xyzrgb[:, 2] > args.crop_z_range[0],
        xyzrgb[:, 2] <= args.crop_z_range[1]
    )
    # fmt: on
    xyzrgb = xyzrgb[within_crop_range]
    return xyzrgb


def render_bev_pair(
    args, building_id: str, floor_id: str, i1: int, i2: int, i2Ti1: Sim2, is_semantics: bool
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Render a pair of texture maps in the same coordinate frame.

    Args:
        args:
        building_id: unique ID of ZinD building.
        floor_id: unique ID of floor of this ZinD building.
        i1: id of panorama 1.
        i2: id of panorama 2.
        i2Ti1: relative pose between the two panoramas i1 and i2, such that p_i2 = i2Ti1 * p_i1.
        is_semantics:

    Returns:
        img1: array of shape (H,W,3) representing BEV texture map rendering for pano 1,
           in the coordinate frame of pano 2.
        img2: array of shape (H,W,3) representing BEV texture map rendering for pano 2.
           Rendering is centered at pano 2's location.
    """
    xyzrgb1 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i1, rgb_fpath=args.img_i1, is_semantics=is_semantics)
    xyzrgb2 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i2, rgb_fpath=args.img_i2, is_semantics=is_semantics)

    print(i2Ti1)

    # HoHoNet center of pano is to -x, but in ZinD center of pano is +y
    R = rotation_utils.rotmat2d(-90)

    xyzrgb1[:, :2] = xyzrgb1[:, :2] @ R.T
    xyzrgb2[:, :2] = xyzrgb2[:, :2] @ R.T

    HOHO_S_ZIND_SCALE_FACTOR = 1.5

    # Move point cloud for i1 into i2's frame.
    xyzrgb1[:, :2] = (xyzrgb1[:, :2] @ i2Ti1.rotation.T) + (i2Ti1.translation * HOHO_S_ZIND_SCALE_FACTOR)

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
    """

    Args:
        args:
        building_id: unique ID of ZinD building.
        floor_id: unique ID of floor of this ZinD building.
        i1: pano 1 ID.
        i2: pano 2 ID.
        i2Ti1: relative pose between the two panoramas i1 and i2, such that p_i2 = i2Ti1 * p_i1.
        is_semantics:

    Returns:
        xyzrgb1: Numpy array of shape (N,6) representing colored point cloud for pano 1.
        xyzrgb2: Numpy array of shape (N,6) representing colored point cloud for pano 2.
    """

    xyzrgb1 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i1, rgb_fpath=args.img_i1, is_semantics=is_semantics)
    xyzrgb2 = get_xyzrgb_from_depth(args, depth_fpath=args.depth_i2, rgb_fpath=args.img_i2, is_semantics=is_semantics)

    # floor_map_json['scale_meters_per_coordinate']
    scale_meters_per_coordinate = 3.7066488344243465
    print(i2Ti1)

    # HoHoNet center of pano is to -x, but in ZinD center of pano is +y
    R = rotation_utils.rotmat2d(-90)

    xyzrgb1[:, :2] = xyzrgb1[:, :2] @ R.T
    xyzrgb2[:, :2] = xyzrgb2[:, :2] @ R.T

    HOHO_S_ZIND_SCALE_FACTOR = 1.5

    xyzrgb1[:, :2] = (xyzrgb1[:, :2] @ i2Ti1.rotation.T) + (
        i2Ti1.translation * HOHO_S_ZIND_SCALE_FACTOR
    )  # * scale_meters_per_coordinate # * np.array([-1,1]))
    # xyzrgb1[:,:2] = i2Ti1.transform_from(xyzrgb1[:,:2]) #

    return xyzrgb1, xyzrgb2


def generate_texture_maps_for_pair(
    img_fpaths_dict: Dict[int, str],
    surface_type: str,
    pair_fpath: str,
    pair_idx: int,
    label_type: str,
    bev_save_root,
    building_id: str,
    floor_id: str,
    depth_save_root: str,
    render_modalities: List[str],
    layout_save_root: str,
    floor_pose_graph: Optional[PoseGraph2d],
) -> None:
    """Generate and save a pair of texture maps for a single pair of panoramas.

    Args:
        img_fpaths_dict: mapping from panorama index to panorama file path.
        surface_type: type of surface to render (floor or ceiling).
        pair_fpath: file path to a serialized .JSON file corresponding to Sim(2) relative pose hypothesis.
        pair_idx: assigned index for ...
        label_type: 
        bev_save_root: Directory where BEV texture maps should be written to (directory will be created at this path.
        building_id: unique ID of ZInD building.
        floor_id: unique ID of floor of ZInD building.
        depth_save_root: Path to where depth maps are stored (or will be saved to, if not computed yet).
        render_modalities: 
        layout_save_root: 
        floor_pose_graph: inferred or GT layout per each panorama (only used if layout will be rendered).
    """
    is_semantics = False
    # if is_semantics:
    #     crop_z_range = [-float('inf'), 2.0]
    # else:

    if surface_type == "floor":
        # Keep everything 1 meter and below the camera
        crop_z_range = [-float("inf"), -1.0]

    elif surface_type == "ceiling":
        # Keep everything 50 cm and above the camera.
        crop_z_range = [0.5, float("inf")]

    i2Ti1 = Sim2.from_json(json_fpath=pair_fpath)

    i1, i2 = Path(pair_fpath).stem.split("_")[:2]
    i1, i2 = int(i1), int(i2)

    img1_fpath = img_fpaths_dict[i1]
    img2_fpath = img_fpaths_dict[i2]

    # e.g. 'door_0_0_identity'
    pair_uuid = Path(pair_fpath).stem.split("__")[-1]

    building_bev_save_dir = f"{bev_save_root}/{label_type}/{building_id}"
    os.makedirs(building_bev_save_dir, exist_ok=True)

    def bev_fname_from_img_fpath(pair_idx: int, pair_uuid: str, surface_type: str, img_fpath: str) -> None:
        """Generate file name for BEV texture map based on panorama image file path."""
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
                "img_i1": img1_fpath,
                # "img_i1": semantic_img1_fpath if is_semantics else img1_fpath,
                "img_i2": img2_fpath,
                # "img_i2": semantic_img2_fpath if is_semantics else img2_fpath,
                "depth_i1": f"{depth_save_root}/{building_id}/{Path(img1_fpath).stem}.depth.png",
                "depth_i2": f"{depth_save_root}/{building_id}/{Path(img2_fpath).stem}.depth.png",
                "scale": 0.001,
                # Throw away top 80 and bottom 80 rows of pixel (too noisy of estimates in these regions).
                "crop_ratio": 80 / 512,
                "crop_z_range": crop_z_range,  # 0.3 # -1.0 # -0.5 # 0.3 # 1.2
            }
        )
        # bev_img = bev_rendering_utils.vis_depth_and_render(args, is_semantics=False)

        # print(f"img1: {img1_fpath}, img2: {img2_fpath}, surface_type: {surface_type}")
        # print(f"bev_img1: {bev_fpath1}, bev_img2: {bev_fpath2}, surface_type: {surface_type}")

        if Path(bev_fpath1).exists() and Path(bev_fpath2).exists():
            print("Both BEV images already exist, skipping...")
            return

        bev_img1, bev_img2 = render_bev_pair(
            args, building_id, floor_id, i1, i2, i2Ti1, is_semantics=False
        )
        if bev_img1 is None or bev_img2 is None:
            # print("skipping...")
            return

        imageio.imwrite(bev_fpath1, bev_img1)
        imageio.imwrite(bev_fpath2, bev_img2)

    if "layout" not in render_modalities:
        return

    # Rasterized-layout rendering below (skipped if only generating texture maps).
    # We only rasterize layout for `floor', not for `ceiling`.
    # If `ceiling', we'll skip, since will be identical rendering to `floor`.
    if surface_type != "floor":
        return

    building_layout_save_dir = f"{layout_save_root}/{label_type}/{building_id}"
    os.makedirs(building_layout_save_dir, exist_ok=True)

    # Change to layout directory.
    layout_fpath1 = f"{building_layout_save_dir}/{bev_fname1}"
    layout_fpath2 = f"{building_layout_save_dir}/{bev_fname2}"

    if Path(layout_fpath1).exists() and Path(layout_fpath2).exists():
        print("Both layout images already exist, skipping...")
        return

    # Skip for ceiling, since would be duplicate.
    layoutimg1, layoutimg2 = rasterize_room_layout_pair(
        i2Ti1=i2Ti1,
        floor_pose_graph=floor_pose_graph,
        building_id=building_id,
        floor_id=floor_id,
        i1=i1,
        i2=i2,
    )
    imageio.imwrite(layout_fpath1, layoutimg1)
    imageio.imwrite(layout_fpath2, layoutimg2)

