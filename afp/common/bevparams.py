"""Parameters for creating bird's eye view images."""

import numpy as np
from argoverse.utils.sim2 import Sim2

# the default resolution for rendering BEV images.

# DEFAULT_BEV_IMG_H_PX = 2000
# DEFAULT_BEV_IMG_W_PX = 2000
# DEFAULT_METERS_PER_PX = 0.005

# DEFAULT_BEV_IMG_H_PX = 1000
# DEFAULT_BEV_IMG_W_PX = 1000
# DEFAULT_METERS_PER_PX = 0.01

DEFAULT_BEV_IMG_H_PX = 500
DEFAULT_BEV_IMG_W_PX = 500
DEFAULT_METERS_PER_PX = 0.02


FULL_RES_METERS_PER_PX = 0.005

# at 2000 x 2000 px image @ 0.005 m/px resolution, this thickness makes sense.
FULL_RES_LINE_WIDTH_PX = 30


class BEVParams:
    def __init__(
        self,
        img_h: int = DEFAULT_BEV_IMG_H_PX,
        img_w: int = DEFAULT_BEV_IMG_W_PX,
        meters_per_px: float = DEFAULT_METERS_PER_PX,
    ) -> None:
        """meters_per_px is resolution

        1000 pixels * (0.005 m / px) = 5 meters in each direction
        """
        self.img_h = img_h
        self.img_w = img_w
        self.meters_per_px = meters_per_px

        # num px in horizontal direction from center
        h_px = img_w / 2

        # num px in vertical direction from center
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

    @property
    def bevimg_Sim2_world(self) -> Sim2:
        """
        m/px -> px/m, then px/m * #meters = #pixels
        """
        grid_xmin, grid_xmax = self.xlims
        grid_ymin, grid_ymax = self.ylims
        return Sim2(R=np.eye(2), t=np.array([-grid_xmin, -grid_ymin]), s=1 / self.meters_per_px)


def test_bevimg_Sim2_world() -> None:
    """Ensure that class constructor works, and Sim(2) generated is correct."""
    # 10 meters x 10 meters in total.
    params = BEVParams(img_h = 20, img_w = 20, meters_per_px = 0.5)

    # fmt: off
    world_pts = np.array(
        [
            [2,2],
            [-5,-5],
            [5,5] # out of bounds
        ]
    )
    # fmt: on
    img_pts = params.bevimg_Sim2_world.transform_from(world_pts)

    # fmt: off
    expected_img_pts = np.array(
        [
            [14,14],
            [0,0],
            [20,20]
        ]
    )
    # fmt: on
    assert np.allclose(img_pts, expected_img_pts)


def get_line_width_by_resolution(resolution: float) -> int:
    """Compute an appropriate polyline width, in pixels, for a specific rendering resolution.
    Note: this is not dependent upon image size -- solely dependent upon image resolution.
    Can have a tiny image at high resolution.

    Args:
        resolution:
    Returns:
        line_width: line width (thickness) in pixels to use for rendering polylines with OpenCV. Must be an integer.
    """
    scale = resolution / FULL_RES_METERS_PER_PX

    # larger scale means lower resolution, so we make the line width more narrow.
    line_width = FULL_RES_LINE_WIDTH_PX / scale

    line_width = round(line_width)
    # must be at least 1 pixel thick.
    return max(line_width, 1)


def test_get_line_width_by_resolution() -> None:
    """Ensure polyline thickness is computed properly."""

    line_width = get_line_width_by_resolution(resolution=0.005)
    assert line_width == 30
    assert isinstance(line_width, int)

    line_width = get_line_width_by_resolution(resolution=0.01)
    assert line_width == 15
    assert isinstance(line_width, int)

    line_width = get_line_width_by_resolution(resolution=0.02)
    assert line_width == 8
    assert isinstance(line_width, int)
