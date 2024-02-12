import glob
import os
import shutil
from collections import defaultdict
from urllib.parse import unquote, urlparse

import supervisely as sly
from dataset_tools.convert import unpack_if_archive
from supervisely.io.fs import get_file_name, get_file_name_with_ext
from supervisely.io.json import load_json_file
from tqdm import tqdm

import src.settings as s


def download_dataset(teamfiles_dir: str) -> str:
    """Use it for large datasets to convert them on the instance"""
    api = sly.Api.from_env()
    team_id = sly.env.team_id()
    storage_dir = sly.app.get_data_dir()

    if isinstance(s.DOWNLOAD_ORIGINAL_URL, str):
        parsed_url = urlparse(s.DOWNLOAD_ORIGINAL_URL)
        file_name_with_ext = os.path.basename(parsed_url.path)
        file_name_with_ext = unquote(file_name_with_ext)

        sly.logger.info(f"Start unpacking archive '{file_name_with_ext}'...")
        local_path = os.path.join(storage_dir, file_name_with_ext)
        teamfiles_path = os.path.join(teamfiles_dir, file_name_with_ext)

        fsize = api.file.get_directory_size(team_id, teamfiles_dir)
        with tqdm(
            desc=f"Downloading '{file_name_with_ext}' to buffer...",
            total=fsize,
            unit="B",
            unit_scale=True,
        ) as pbar:
            api.file.download(team_id, teamfiles_path, local_path, progress_cb=pbar)
        dataset_path = unpack_if_archive(local_path)

    if isinstance(s.DOWNLOAD_ORIGINAL_URL, dict):
        for file_name_with_ext, url in s.DOWNLOAD_ORIGINAL_URL.items():
            local_path = os.path.join(storage_dir, file_name_with_ext)
            teamfiles_path = os.path.join(teamfiles_dir, file_name_with_ext)

            if not os.path.exists(get_file_name(local_path)):
                fsize = api.file.get_directory_size(team_id, teamfiles_dir)
                with tqdm(
                    desc=f"Downloading '{file_name_with_ext}' to buffer...",
                    total=fsize,
                    unit="B",
                    unit_scale=True,
                ) as pbar:
                    api.file.download(team_id, teamfiles_path, local_path, progress_cb=pbar)

                sly.logger.info(f"Start unpacking archive '{file_name_with_ext}'...")
                unpack_if_archive(local_path)
            else:
                sly.logger.info(
                    f"Archive '{file_name_with_ext}' was already unpacked to '{os.path.join(storage_dir, get_file_name(file_name_with_ext))}'. Skipping..."
                )

        dataset_path = storage_dir
    return dataset_path


def count_files(path, extension):
    count = 0
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith(extension):
                count += 1
    return count


def convert_and_upload_supervisely_project(
    api: sly.Api, workspace_id: int, project_name: str
) -> sly.ProjectInfo:
    ### Function should read local dataset and upload it to Supervisely project, then return project info.###
    images_path = "/home/alex/DATASETS/TODO/Argoverse/archive/Argoverse-1.1/tracking"
    bboxes_path = "/home/alex/DATASETS/TODO/Argoverse/archive/Argoverse-HD/annotations"
    batch_size = 30
    anns_ext = ".json"

    def create_ann(image_path):
        labels = []

        subfolder_value = image_path.split("/")[-3]
        subfolder = sly.Tag(subfolder_meta, value=subfolder_value)

        # image_np = sly.imaging.image.read(image_path)[:, :, 0]
        img_height = 1200  # image_np.shape[0]
        img_wight = 1920  # image_np.shape[1]

        ann_data = image_path_to_ann_data.get(image_path)
        if ann_data is not None:
            for curr_ann_data in ann_data:
                category_id = curr_ann_data[0]
                track_value = curr_ann_data[-1]
                track = sly.Tag(track_meta, value=track_value)

                bbox_coord = curr_ann_data[1]
                rectangle = sly.Rectangle(
                    top=int(bbox_coord[1]),
                    left=int(bbox_coord[0]),
                    bottom=int(bbox_coord[1] + bbox_coord[3]),
                    right=int(bbox_coord[0] + bbox_coord[2]),
                )
                label_rectangle = sly.Label(rectangle, idx_to_obj_class[category_id], tags=[track])
                labels.append(label_rectangle)

        return sly.Annotation(img_size=(img_height, img_wight), labels=labels, img_tags=[subfolder])

    idx_to_obj_class = {
        0: sly.ObjClass("person", sly.Rectangle),
        1: sly.ObjClass("bicycle", sly.Rectangle),
        2: sly.ObjClass("car", sly.Rectangle),
        3: sly.ObjClass("motorcycle", sly.Rectangle),
        4: sly.ObjClass("bus", sly.Rectangle),
        5: sly.ObjClass("truck", sly.Rectangle),
        6: sly.ObjClass("traffic light", sly.Rectangle),
        7: sly.ObjClass("stop sign", sly.Rectangle),
    }

    track_meta = sly.TagMeta("track", sly.TagValueType.ANY_NUMBER)
    subfolder_meta = sly.TagMeta("sequence", sly.TagValueType.ANY_STRING)

    project = api.project.create(workspace_id, project_name, change_name_if_conflict=True)
    meta = sly.ProjectMeta(
        obj_classes=list(idx_to_obj_class.values()), tag_metas=[track_meta, subfolder_meta]
    )
    api.project.update_meta(project.id, meta.to_json())

    for ds_name in ["train", "val", "test"]:
        dataset = api.dataset.create(project.id, ds_name, change_name_if_conflict=True)
        curr_images_path = os.path.join(images_path, ds_name)

        image_id_to_path = {}
        seq_id_to_path = {}
        image_path_to_ann_data = defaultdict(list)

        curr_images_path = os.path.join(images_path, ds_name)

        if ds_name != "test":
            curr_bboxes_path = os.path.join(bboxes_path, ds_name + anns_ext)
            ann = load_json_file(curr_bboxes_path)
            for idx, curr_seq_info in enumerate(ann["seq_dirs"]):
                seq_id_to_path[idx] = curr_seq_info
            for curr_image_info in ann["images"]:
                curr_image_path = os.path.join(
                    images_path, seq_id_to_path[curr_image_info["sid"]], curr_image_info["name"]
                )
                image_id_to_path[curr_image_info["id"]] = curr_image_path

            for curr_ann_data in ann["annotations"]:
                image_id = curr_ann_data["image_id"]
                image_path_to_ann_data[image_id_to_path[image_id]].append(
                    [curr_ann_data["category_id"], curr_ann_data["bbox"], curr_ann_data["track"]]
                )

        images_pathes = glob.glob(curr_images_path + "/*/*/*.jpg")

        progress = sly.Progress("Create dataset {}".format(ds_name), len(images_pathes))

        for img_pathes_batch in sly.batched(images_pathes, batch_size=batch_size):
            img_names_batch = [get_file_name_with_ext(im_path) for im_path in img_pathes_batch]

            img_infos = api.image.upload_paths(dataset.id, img_names_batch, img_pathes_batch)
            img_ids = [im_info.id for im_info in img_infos]

            if ds_name != "test":
                anns = [create_ann(image_path) for image_path in img_pathes_batch]
                api.annotation.upload_anns(img_ids, anns)

            progress.iters_done_report(len(img_names_batch))

    return project
