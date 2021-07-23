
"""
Dataset that reads ZinD data, and feeds it to a Pytorch dataloader.
"""

import glob
import logging
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

import imageio
from torch.utils.data import Dataset
from torch import Tensor

TRAIN_SPLIT_FRACTION = 0.85


def pair_idx_from_fpath(fpath: str) -> int:
    """ """
    fname_stem = Path(fpath).stem

    parts = fname_stem.split("___")[0].split('_')
    return int(parts[1])


def test_pair_idx_from_fpath() -> None:
    """ """
    #fpath = "/Users/johnlam/Downloads/DGX-rendering-2021_06_25/ZinD_BEV_RGB_only_2021_06_25/gt_alignment_approx/000/pair_10_floor_rgb_floor_01_partial_room_01_pano_15.jpg"
    fpath = '/mnt/data/johnlam/ZinD_BEV_RGB_only_2021_07_14_v3/gt_alignment_approx/1394/pair_24___opening_0_0_identity_ceiling_rgb_floor_01_partial_room_01_pano_18.jpg'
    pair_idx = pair_idx_from_fpath(fpath)

    assert pair_idx == 24


def pano_id_from_fpath(fpath: str) -> int:
    """ """
    fname_stem = Path(fpath).stem
    parts = fname_stem.split("_")
    return int(parts[-1])


def test_pano_id_from_fpath() -> None:
    """ """
    #fpath = "/Users/johnlam/Downloads/DGX-rendering-2021_06_25/ZinD_BEV_RGB_only_2021_06_25/gt_alignment_approx/242/pair_58_floor_rgb_floor_01_partial_room_13_pano_25.jpg"
    fpath = '/mnt/data/johnlam/ZinD_BEV_RGB_only_2021_07_14_v3/gt_alignment_approx/1394/pair_24___opening_0_0_identity_ceiling_rgb_floor_01_partial_room_01_pano_18.jpg'
    pano_id = pano_id_from_fpath(fpath)
    assert pano_id == 18


def get_4tuples_from_list(fpaths: List[str], label_idx: int) -> List[Tuple[str, str, str, str, int]]:
    """Given paths for a single floor of single building, extract training/test metadata from the filepaths.

    Note: pair_idx is unique for a (building, floor) but not for a building.

    Args:
        fpaths:
        label_idx: index of ground truth class to associate with 4-tuple
    """

    # put each file path into a dictionary, to group them
    pairidx_to_fpath_dict = defaultdict(list)

    for fpath in fpaths:
        pair_idx = pair_idx_from_fpath(fpath)
        pairidx_to_fpath_dict[pair_idx] += [fpath]

    tuples = []
    # extract the valid values -- must be a 4-tuple
    for pair_idx, pair_fpaths in pairidx_to_fpath_dict.items():
        if len(pair_fpaths) != 4:
            continue

        pair_fpaths.sort()
        fp0, fp1, fp2, fp3 = pair_fpaths

        pano1_id = pano_id_from_fpath(fp0)
        pano2_id = pano_id_from_fpath(fp1)

        assert pano1_id != pano2_id

        # make sure each tuple is in sorted order (floor,floor) and (ceiling,ceiling)
        assert "_ceiling_rgb_" in Path(fp0).name
        assert "_ceiling_rgb_" in Path(fp1).name

        assert "_floor_rgb_" in Path(fp2).name
        assert "_floor_rgb_" in Path(fp3).name

        assert f"_pano_{pano1_id}.jpg" in Path(fp0).name
        assert f"_pano_{pano2_id}.jpg" in Path(fp1).name

        assert f"_pano_{pano1_id}.jpg" in Path(fp2).name
        assert f"_pano_{pano2_id}.jpg" in Path(fp3).name

        """
        # make sure nothing corrupted enters the dataset
        try:
            img = imageio.imread(fp0)
            img = imageio.imread(fp1)
            img = imageio.imread(fp2)
            img = imageio.imread(fp3)
        except:
            print("Corrupted in ", fp0, fp1, fp2, fp3)
            continue
        """

        tuples += [(fp0, fp1, fp2, fp3, label_idx)]

    return tuples


def get_available_building_ids(dataset_root: str) -> List[str]:
    """ """
    building_ids = [Path(fpath).stem for fpath in glob.glob(f"{dataset_root}/*") if Path(fpath).is_dir()]
    building_ids = sorted(building_ids, key=lambda x: int(x))
    return building_ids


def make_dataset(split: str, args) -> List[Tuple[str, str, str, str, int]]:
    """
    Note: is_match = 1 means True.
    """
    if not Path(args.data_root).exists():
        raise RuntimeError("Dataset root directory does not exist on this machine. Exitting...")

    data_list = []
    logging.info(f"Populating data list for split {split}...")

    # TODO: search from both folders instead
    available_building_ids = get_available_building_ids(dataset_root=f"{args.data_root}/gt_alignment_approx")

    # split into train and val now --> keep 85% of building_id's in train
    #split_idx = int(len(available_building_ids) * TRAIN_SPLIT_FRACTION)

    val_building_ids = ['1635', '1584', '1583', '1578', '1530', '1490', '1442', '1626', '1427', '1394']
    train_building_ids = set(available_building_ids) - set(val_building_ids)
    train_building_ids = list(train_building_ids)

    # TODO: remove hard-coding
    split_idx = 0

    if split == "train":
        split_building_ids = train_building_ids #[:split_idx]
    elif split in "val":
        split_building_ids = val_building_ids # trainval_building_ids[split_idx:]
    elif split == "test":
        raise RuntimeError
        #split_building_ids == 

    label_dict = {"gt_alignment_approx": 1, "incorrect_alignment": 0}  # is_match = True

    for label_name, label_idx in label_dict.items():
        for building_id in split_building_ids:

            logging.info(
                f"\t{label_name}: On building {building_id} -- so far, for split {split}, found {len(data_list)} tuples..."
            )

            for floor_id in ["floor_00", "floor_01", "floor_02", "floor_03", "floor_04"]:

                fpaths = glob.glob(f"{args.data_root}/{label_name}/{building_id}/pair_*___*_rgb_{floor_id}_*.jpg")
                # here, pair_id will be unique

                tuples = get_4tuples_from_list(fpaths, label_idx)
                if len(tuples) == 0:
                    continue
                data_list.extend(tuples)

    logging.info(f"Data list for split {split} has {len(data_list)} tuples.")
    return data_list


class ZindData(Dataset):
    """ """

    def __init__(self, split: str, transform, args):
        """ """
        self.transform = transform
        self.data_list = make_dataset(split, args)

    def __len__(self) -> int:
        """ """
        return len(self.data_list)

    def __getitem__(self, index: int) -> Tuple[Tensor, Tensor, Tensor, Tensor, int, str, str, str, str]:
        """
        Note: is_match = 1 means True.
        """
        x1_fpath, x2_fpath, x3_fpath, x4_fpath, is_match = self.data_list[index]

        x1 = imageio.imread(x1_fpath)
        x2 = imageio.imread(x2_fpath)
        x3 = imageio.imread(x3_fpath)
        x4 = imageio.imread(x4_fpath)

        x1, x2, x3, x4 = self.transform(x1, x2, x3, x4)

        return x1, x2, x3, x4, is_match, x1_fpath, x2_fpath, x3_fpath, x4_fpath


def test_ZindData_constructor() -> None:
    """ """
    transform = None

    from types import SimpleNamespace
    args = SimpleNamespace(**{
        "data_root": "/mnt/data/johnlam/ZinD_BEV_RGB_only_2021_07_14_v3"
    })
    dataset = ZindData(split="val", transform=transform, args=args)
    assert len(dataset.data_list) > 0

def test_ZindData_getitem() -> None:
    """ """
    pass

if __name__ == '__main__':
    """ """
    test_ZindData_constructor()

