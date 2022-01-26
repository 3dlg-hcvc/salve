"""
Enhanced Correlation Coefficient (ECC) 

"Parametric Image Alignment using Enhanced Correlation Coefficient Maximization"
by Georgios D. Evangelidis and Emmanouil Z. Psarakis 2008
http://xanthippi.ceid.upatras.gr/people/evangelidis/george_files/PAMI_2008.pdf

Other option: RASL, https://github.com/welch/rasl
                    https://github.com/kokerf/imageAlign
                    https://github.com/arashabedin/Image-Alignment
"""

from typing import Tuple

import cv2
import imageio
import matplotlib.pyplot as plt
import numpy as np
import skimage

from numpy.fft import fft2, ifft2


def find_keypoint_matches_sift(im1_gray: np.ndarray, im2_gray: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Args:
        im1_gray
        im2_gray

    Returns:
        pts1: matching keypoints from im1
        pts2: matching keypoints from im2
    """
    opencv_obj = cv2.SIFT_create()

    import pdb

    pdb.set_trace()

    compute_mask = lambda im: (im != 0).astype(np.uint8)

    keypoints1, descriptors_i1 = opencv_obj.detectAndCompute(im1_gray, mask=compute_mask(im1_gray))
    keypoints2, descriptors_i2 = opencv_obj.detectAndCompute(im2_gray, mask=compute_mask(im2_gray))

    coordinates1 = np.array([([kp.pt[0], kp.pt[1]]) for kp in keypoints1])
    coordinates2 = np.array([([kp.pt[0], kp.pt[1]]) for kp in keypoints2])

    if descriptors_i1.size == 0 or descriptors_i2.size == 0:
        return np.array([]), np.array([])

    # we will have to remove NaNs by ourselves
    valid_idx_i1 = np.nonzero(~(np.isnan(descriptors_i1).any(axis=1)))[0]
    valid_idx_i2 = np.nonzero(~(np.isnan(descriptors_i2).any(axis=1)))[0]

    descriptors_1 = descriptors_i1[valid_idx_i1]
    descriptors_2 = descriptors_i2[valid_idx_i2]

    # run OpenCV's matcher
    bf = cv2.BFMatcher(normType=cv2.NORM_L2, crossCheck=True)
    matches = bf.match(descriptors_i1, descriptors_i2)
    matches = sorted(matches, key=lambda r: r.distance)

    imMatches = cv2.drawMatches(im1_gray, keypoints1, im2_gray, keypoints2, matches[:10], None)
    plt.imshow(imMatches)
    plt.show()

    match_indices = np.array([[m.queryIdx, m.trainIdx] for m in matches]).astype(np.int32)

    if match_indices.size == 0:
        return np.array([])

    # remap them back
    pts1 = coordinates1[valid_idx_i1][match_indices[:, 0]]
    pts2 = coordinates2[valid_idx_i2][match_indices[:, 1]]

    return pts1, pts2


def find_keypoint_matches_orb(im1_gray: np.ndarray, im2_gray: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """ """
    # Detect ORB features and compute descriptors.
    orb = cv2.ORB_create(max_features)
    keypoints1, descriptors1 = orb.detectAndCompute(im1Gray, None)
    keypoints2, descriptors2 = orb.detectAndCompute(im2Gray, None)

    # Match features.
    matcher = cv2.DescriptorMatcher_create(cv2.DESCRIPTOR_MATCHER_BRUTEFORCE_HAMMING)
    matches = matcher.match(descriptors1, descriptors2, None)

    # Sort matches by score
    matches.sort(key=lambda x: x.distance, reverse=False)

    # Remove not so good matches
    numGoodMatches = int(len(matches) * feature_retention)
    matches = matches[:numGoodMatches]

    # Draw top matches
    imMatches = cv2.drawMatches(im1, keypoints1, im2, keypoints2, matches, None)
    # cv2.imwrite("matches.jpg", imMatches)

    # Extract location of good matches
    points1 = np.zeros((len(matches), 2), dtype=np.float32)
    points2 = np.zeros((len(matches), 2), dtype=np.float32)

    for i, match in enumerate(matches):
        points1[i, :] = keypoints1[match.queryIdx].pt
        points2[i, :] = keypoints2[match.trainIdx].pt
    return points1, points2


# (ORB) feature based alignment
def feature_align(im1: np.ndarray, im2: np.ndarray) -> None:
    """
    Args:
        im1:
        im2:
    """
    max_features = 50000

    # Convert images to grayscale
    im1_gray = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)
    im2_gray = cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)

    points1, points2 = find_keypoint_matches_sift(im1_gray, im2_gray)

    # Find homography
    H, mask = cv2.findHomography(points1, points2, cv2.RANSAC)

    # Use homography
    height, width, channels = im2.shape
    im1_aligned = cv2.warpPerspective(src=im1, M=H, dsize=(width, height))

    # Show final output
    plt.subplot(1, 3, 1)
    plt.title("Image 1")
    plt.imshow(im1)

    plt.subplot(1, 3, 2)
    plt.title("Image 2")
    plt.imshow(im2)

    plt.subplot(1, 3, 3)
    plt.title("Aligned Image 1")
    plt.imshow(im1_aligned)

    plt.show()

    return im1Reg, h


def photometric_alignment(im1: np.ndarray, im2: np.ndarray) -> None:
    """
    Args:
        im1:
        im2:

    Returns:
        TODO
    """
    # Convert images to grayscale
    im1_gray = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)
    im2_gray = cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)

    # Find size of image1
    H, W, _ = im1.shape

    # Define the motion model
    # warp_mode = cv2.MOTION_TRANSLATION # (x,y)
    # warp_mode = cv2.MOTION_EUCLIDEAN # (x,y,theta)
    # warp_mode = cv2.MOTION_AFFINE # (R,t, scale, shear)
    warp_mode = cv2.MOTION_HOMOGRAPHY  # 8 params

    # Define 2x3 or 3x3 matrices and initialize the matrix to identity
    if warp_mode == cv2.MOTION_HOMOGRAPHY:
        warp_matrix = np.eye(3, 3, dtype=np.float32)
    else:
        warp_matrix = np.eye(2, 3, dtype=np.float32)

    # Specify the number of iterations.
    number_of_iterations = 5000

    # Specify the threshold of the increment
    # in the correlation coefficient between two iterations
    termination_eps = 1e-10

    # Define termination criteria
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, number_of_iterations, termination_eps)

    # wherever we have non-zero pixel intensities, indicates valid values of inputImage.
    input_mask = (im2[:, :, 0] != 0).astype(np.uint8)
    import pdb

    pdb.set_trace()

    plt.subplot(1, 2, 1)
    plt.imshow(im2)

    plt.subplot(1, 2, 2)
    plt.imshow(input_mask)
    plt.title("Mask")
    plt.show()

    # TODO: try both with and without the input mask. For within-room matching, mask may actually hurt, if black matters.

    # Run the ECC algorithm. The results are stored in warp_matrix.
    (cc, warp_matrix) = cv2.findTransformECC(
        templateImage=im1_gray,
        inputImage=im2_gray,
        warpMatrix=warp_matrix,
        motionType=warp_mode,
        criteria=criteria,
        inputMask=input_mask,
    )

    import pdb

    pdb.set_trace()

    if warp_mode == cv2.MOTION_HOMOGRAPHY:
        # Use warpPerspective for Homography
        im2_aligned = cv2.warpPerspective(
            src=im2, M=warp_matrix, dsize=(W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP
        )

    else:
        # Use warpAffine for Translation, Euclidean and Affine
        im2_aligned = cv2.warpAffine(
            src=im2, M=warp_matrix, dsize=(W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP
        )

    # Show final output
    plt.subplot(1, 3, 1)
    plt.title("Image 1")
    plt.imshow(im1)

    plt.subplot(1, 3, 2)
    plt.title("Image 2")
    plt.imshow(im2)

    plt.subplot(1, 3, 3)
    plt.title("Aligned Image 2")
    plt.imshow(im2_aligned)

    plt.show()


def get_gradient(im: np.ndarray) -> np.ndarray:
    """
    Args:
        im1

    Returns:
        grad: image gradient
    """
    # Calculate the x and y gradients using Sobel operator
    grad_x = cv2.Sobel(im, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(im, cv2.CV_32F, 0, 1, ksize=3)

    # Combine the two gradients
    grad = cv2.addWeighted(np.absolute(grad_x), 0.5, np.absolute(grad_y), 0.5, 0)
    return grad


def gradient_based_alignment(im1: np.ndarray, im2: np.ndarray) -> None:
    """
    Reference: https://docs.opencv.org/3.4/dd/d93/samples_2cpp_2image_alignment_8cpp-example.html#a39
               https://learnopencv.com/image-alignment-ecc-in-opencv-c-python/

    Args:
        im1
        im2

    Returns:
        TODO
    """
    H, W, _ = im1.shape

    im1_gray = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)
    im2_gray = cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)

    # Allocate space for aligned image
    im_aligned = np.zeros((H, W, 3), dtype=np.uint8)

    # Define the motion model
    warp_mode = cv2.MOTION_TRANSLATION  # (x,y)
    # warp_mode = cv2.MOTION_EUCLIDEAN # (x,y,theta)
    # warp_mode = cv2.MOTION_AFFINE # (R,t, scale, shear)
    # warp_mode = cv2.MOTION_HOMOGRAPHY # 8 params

    # Set the warp matrix to identity.
    if warp_mode == cv2.MOTION_HOMOGRAPHY:
        warp_matrix = np.eye(3, 3, dtype=np.float32)
    else:
        warp_matrix = np.eye(2, 3, dtype=np.float32)

    # Set the stopping criteria for the algorithm.
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 5000, 1e-10)

    # Warp the image 1 to image2 (or vice versa TODO: double check order)

    im1_grad = get_gradient(im1_gray)
    im2_grad = get_gradient(im2_gray)

    # plt.subplot(1,3,1)
    # plt.imshow(im1_grad)

    # plt.subplot(1,3,2)
    # plt.imshow(im2_grad)
    # plt.show()

    input_mask = np.ones((H, W), dtype=np.uint8)

    (cc, warp_matrix) = cv2.findTransformECC(
        templateImage=im1_grad,
        inputImage=im2_grad,  # target
        warpMatrix=warp_matrix,
        motionType=warp_mode,
        criteria=criteria,
        inputMask=input_mask,
    )

    # now, warp the target image.
    if warp_mode == cv2.MOTION_HOMOGRAPHY:
        # Use Perspective warp when the transformation is a Homography
        im2_aligned = cv2.warpPerspective(
            src=im2_gray, M=warp_matrix, dsize=(W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP
        )
    else:
        # Use Affine warp when the transformation is not a Homography
        im2_aligned = cv2.warpAffine(im2_gray, warp_matrix, (W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
    print("Warp matrix: ", warp_matrix)

    # Show final output
    plt.subplot(1, 3, 1)
    plt.imshow(im1)
    plt.title("Image 1")

    plt.subplot(1, 3, 2)
    plt.imshow(im2)
    plt.title("Image 2")

    plt.subplot(1, 3, 3)
    plt.imshow(im2_aligned)
    plt.title("Aligned Image 2")

    plt.show()


def rotation_cross_correlation_align(im1: np.ndarray, im2: np.ndarray):
    """Try all discretizations, from 0-360."""

    # Convert images to grayscale
    im1_gray = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)
    im2_gray = cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)
    height, width = im1_gray.shape[0:2]

    values = np.ones(360)

    for i in range(0, 360):
        rotationMatrix = cv2.getRotationMatrix2D((width / 2, height / 2), i, 1)
        rot = cv2.warpAffine(im2_red, rotationMatrix, (width, height))

        # now use cross-correlation
        values[i] = np.mean(im1_gray - rot)

    rotationMatrix = cv2.getRotationMatrix2D((width / 2, height / 2), np.argmin(values), 1)
    rotated = cv2.warpAffine(im2, rotationMatrix, (width, height))

    return rotated, rotationMatrix


def align_by_fft_phase_correlation(im0: np.ndarray, im1: np.ndarray):
    """FFT phase correlation. Translation only.

    The Fourier transform of a convolution of two signals is the pointwise product of their Fourier transforms.

    Kuglin, C. D. and Hines, D. C., 1975. The Phase Correlation Image Alignment Method

    "An FFT-Based Technique for Translation, Rotation, and Scale-Invariant Image Registration"
    B. Srinivasa Reddy and B. N. Chatterji
    https://ieeexplore.ieee.org/iel4/83/11100/00506761.pdf?casa_token=GwaKJH7Tb7YAAAAA:w1gRMPRIWi5VGfYz343ZUxg3Sm8ASt9kBmcT72DNGEJT9f0EA5ojd3CqORN_SiyfJEkvYKpM

    References: https://github.com/khufkens/align_images/blob/master/align_images.py
                https://github.com/michaelting/Phase_Correlation/blob/master/phase_corr.py#L31
                https://github.com/YoshiRi/ImRegPOC
                https://cgcooke.github.io/Blog/computer%20vision/nuketown84/2020/12/19/FFT-Phase-Correlation.html
    """
    H, W, C = im0.shape

    # Convert images to grayscale
    im0 = cv2.cvtColor(im0, cv2.COLOR_BGR2GRAY)
    im1 = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY)

    H, W = im0.shape

    f0 = np.fft.fft2(im0)
    f1 = np.fft.fft2(im1)
    # calculate cross-power spectrum.
    # cross_power_spectrum = (f0 * f1.conjugate()) / (abs(f0) * abs(f1))
    cross_power_spectrum = (f0 * f1.conjugate()) / (abs(f0) * abs(f1.conjugate()))
    ir = abs(np.fft.ifft2(cross_power_spectrum))

    # find location of peak, converting 1d index to 2d index (By default, the index is into the flattened array).
    ty, tx = np.unravel_index(np.argmax(ir), (H, W))
    if ty > H // 2:
        ty -= H
    if tx > W // 2:
        tx -= W

    t = np.array([tx, ty])

    warp_matrix = np.eye(2, 3)
    warp_matrix[:, 2] = -t
    im1_aligned = cv2.warpAffine(src=im1, M=warp_matrix, dsize=(W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

    print("Translation: ", t)

    # Show final output
    plt.subplot(1, 3, 1)
    plt.title("Image 0")
    plt.imshow(im0)

    plt.subplot(1, 3, 2)
    plt.title("Image 1")
    plt.imshow(im1)

    plt.subplot(1, 3, 3)
    plt.title("Aligned Image 1")
    plt.imshow(im1_aligned)

    plt.show()


def phase_correlation_scikit_image(im1: np.ndarray, im2: np.ndarray):
    """
    Reference: https://scikit-image.org/docs/stable/api/skimage.registration.html#skimage.registration.phase_cross_correlation
    See source: https://github.com/scikit-image/scikit-image/blob/v0.19.0/skimage/registration/_phase_cross_correlation.py#L112-L313

    Dirk Padfield. Masked Object Registration in the Fourier Domain. IEEE Transactions on Image Processing, vol. 21(5), pp. 2706-2718 (2012).
    D. Padfield. “Masked FFT registration”. In Proc. Computer Vision and Pattern Recognition, pp. 2918-2925 (2010).

    See: https://www.mathworks.com/matlabcentral/fileexchange/18401-efficient-subpixel-image-registration-by-cross-correlation
    [1] Manuel Guizar-Sicairos, Samuel T. Thurman, and James R. Fienup, "Efficient subpixel image registration algorithms," Opt. Lett. 33, 156-158 (2008).
    """
    H, W, C = im1.shape

    shifts, error, phase_diff = skimage.registration.phase_cross_correlation(reference_image=im1, moving_image=im2)
    ty, tx, tc = shifts

    t = np.array([tx, ty])

    warp_matrix = np.eye(2, 3)
    warp_matrix[:, 2] = -t
    im2_aligned = cv2.warpAffine(src=im2, M=warp_matrix, dsize=(W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

    print("Translation: ", t)

    # Show final output
    plt.subplot(1, 3, 1)
    plt.title("Image 1")
    plt.imshow(im1)

    plt.subplot(1, 3, 2)
    plt.title("Image 2")
    plt.imshow(im2)

    plt.subplot(1, 3, 3)
    plt.title("Aligned Image 2")
    plt.imshow(im2_aligned)

    blended = blend_images(im1, im2_aligned)
    plt.imshow(blended)

    plt.show()


def blend_images(im1: np.ndarray, im2: np.ndarray) -> np.ndarray:
    """ """
    mean_img = (im1.astype(np.float32) + im2.astype(np.float32)) / 2
    return mean_img.astype(np.uint8)


if __name__ == "__main__":

    fpath1 = "/Users/johnlambert/Downloads/salve_data/ZinD_Bridge_API_BEV_2021_10_20_lowres/gt_alignment_approx/0382/pair_154___door_1_0_rotated_ceiling_rgb_floor_03_partial_room_03_pano_57.jpg"
    fpath2 = "/Users/johnlambert/Downloads/salve_data/ZinD_Bridge_API_BEV_2021_10_20_lowres/gt_alignment_approx/0382/pair_154___door_1_0_rotated_ceiling_rgb_floor_03_partial_room_07_pano_56.jpg"

    # fpath1 = "/Users/johnlambert/Downloads/salve_data/ZinD_Bridge_API_BEV_2021_10_20_lowres/incorrect_alignment/0382/pair_39___opening_2_2_identity_floor_rgb_floor_02_partial_room_07_pano_11.jpg"
    # fpath2 = "/Users/johnlambert/Downloads/salve_data/ZinD_Bridge_API_BEV_2021_10_20_lowres/incorrect_alignment/0382/pair_39___opening_2_2_identity_floor_rgb_floor_02_partial_room_02_pano_62.jpg"

    # fpath1 = "/Users/johnlambert/Downloads/salve_data/ZinD_Bridge_API_BEV_2021_10_20_lowres/incorrect_alignment/0382/pair_779___opening_1_2_identity_floor_rgb_floor_02_partial_room_02_pano_62.jpg"
    # fpath2 = "/Users/johnlambert/Downloads/salve_data/ZinD_Bridge_API_BEV_2021_10_20_lowres/incorrect_alignment/0382/pair_779___opening_1_2_identity_floor_rgb_floor_02_partial_room_02_pano_9.jpg"

    # fpath1 = "/Users/johnlambert/Desktop/im1_door_cropped.png"
    # fpath2 = "/Users/johnlambert/Desktop/im2_door_cropped.png"

    # fpath1 = "/Users/johnlambert/Desktop/im1_crane_mast_bottom_cropped.png"
    # fpath2 = "/Users/johnlambert/Desktop/im2_crane_mast_bottom_cropped.png"

    # Read the images to be aligned
    # im1 = cv2.imread(fpath1)
    # im2 = cv2.imread(fpath2)
    im1 = imageio.imread(fpath1)
    im2 = imageio.imread(fpath2)

    # photometric_alignment(im1, im2)
    # feature_align(im1, im2)
    # rotation_cross_correlation_align(im1, im2)
    # gradient_based_alignment(im1, im2)

    # align_by_fft_phase_correlation(im1, im2)
    phase_correlation_scikit_image(im1, im2)
