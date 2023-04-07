import io
import os
import pathlib
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Union

import numpy as np
import tensorflow as tf
import torch

from wandb import util

from .media import Media, MediaSequence, register

if TYPE_CHECKING:
    import moviepy.video.io.ImageSequenceClip

    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run


class Video(Media):
    """A video object. This object can be used to log videos to W&B."""

    OBJ_TYPE = "video-file"
    OBJ_ARTIFACT_TYPE = "video-file"
    RELATIVE_PATH = pathlib.Path("media") / "videos"
    DEFAULT_FORMAT = "GIF"

    SUPPORTED_FORMATS = ["mp4", "webm", "gif", "ogg"]

    _caption: Optional[str]
    _width: Optional[int]
    _height: Optional[int]

    def __init__(
        self,
        data_or_path,
        caption: Optional[str] = None,
        fps: int = 4,
        format: Optional[str] = None,
    ) -> None:
        super().__init__()
        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, io.BytesIO):
            self.from_buffer(data_or_path, format)
        elif isinstance(data_or_path, np.ndarray):
            self.from_numpy(data_or_path, fps=fps, format=format)
        elif isinstance(data_or_path, torch.Tensor):
            self.from_torch(data_or_path, fps=fps, format=format)
        elif isinstance(data_or_path, tf.Tensor):
            self.from_tensorflow(data_or_path, fps=fps, format=format)
        else:
            raise ValueError(f"Unsupported type: {type(data_or_path)}")

        self._caption = caption
        # todo: add width height when available
        self._width = None
        self._height = None

    def to_json(self) -> Dict[str, Any]:
        serialized = super().to_json()
        # todo: add width height when available
        serialized.update({"caption": self._caption})
        return serialized

    def bind_to_run(
        self, run: "Run", *namespace: str, name: Optional[str] = None
    ) -> None:
        return super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )

    def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
        serialized = super().bind_to_artifact(artifact)
        if self._width is not None:
            serialized["width"] = self._width
        if self._height is not None:
            serialized["height"] = self._height
        if self._caption:
            serialized["caption"] = self._caption
        return serialized

    def from_buffer(self, buffer: io.BytesIO, format: Optional[str] = None) -> None:
        self._format = (format or self.DEFAULT_FORMAT).lower()
        with self.path.save(suffix=f".{self._format}") as path:
            with open(path, "wb") as f:
                f.write(buffer.read())

    def from_path(self, path: Union[str, os.PathLike]) -> None:
        with self.path.save(path) as path:
            self._format = path.suffix[1:]
            assert (
                self._format in self.SUPPORTED_FORMATS
            ), f"Unsupported format: {self._format}"

    def from_numpy(self, array: "np.ndarray", fps: int, format: Optional[str]) -> None:
        self._format = (format or self.DEFAULT_FORMAT).lower()
        with self.path.save(suffix=f".{self._format}") as path:
            array = prepare_data(array)
            write_file(array, path, fps=fps, format=self._format)

    def from_tensorflow(
        self, tensor: "tf.Tensor", fps: int, format: Optional[str]
    ) -> None:
        array = tensor.numpy()  # type: ignore
        self.from_numpy(array, fps=fps, format=format)

    def from_torch(
        self, tensor: "torch.Tensor", fps: int, format: Optional[str]
    ) -> None:
        array = tensor.numpy()
        self.from_numpy(array, fps=fps, format=format)


def prepare_data(data: "np.ndarray") -> "np.ndarray":
    if data.ndim < 4:
        raise ValueError(
            "Video must be atleast 4 dimensions: time, channels, height, width"
        )
    if data.ndim == 4:
        data = data.reshape(1, *data.shape)
    b, t, c, h, w = data.shape

    if data.dtype != np.uint8:
        data = data.astype(np.uint8)

    def is_power2(num: int) -> bool:
        return num != 0 and ((num & (num - 1)) == 0)

    # pad to nearest power of 2, all at once
    if not is_power2(data.shape[0]):
        len_addition = int(2 ** data.shape[0].bit_length() - data.shape[0])
        data = np.concatenate(
            (data, np.zeros(shape=(len_addition, t, c, h, w))), axis=0
        )

    n_rows = 2 ** ((b.bit_length() - 1) // 2)
    n_cols = data.shape[0] // n_rows

    data = np.reshape(data, newshape=(n_rows, n_cols, t, c, h, w))
    data = np.transpose(data, axes=(2, 0, 4, 1, 5, 3))
    data = np.reshape(data, newshape=(t, n_rows * h, n_cols * w, c))
    return data


def write_gif(
    clip: "moviepy.video.io.ImageSequenceClip.ImageSequenceClip",
    path: str,
    fps: Optional[int] = None,
) -> None:
    imageio = util.get_module(
        "imageio",
        required='wandb.Video requires imageio when passing raw data. Install with "pip install imageio"',
    )

    fps = clip.fps or fps
    assert fps is not None, "FPS must be specified"
    writer = imageio.save(
        path, duration=1.0 / fps, quantizer=0, palettesize=256, loop=0
    )

    for frame in clip.iter_frames(fps=fps, dtype="uint8"):
        writer.append_data(frame)

    writer.close()


def write_file(array, path, fps, format) -> None:
    from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

    clip = ImageSequenceClip(list(array), fps=fps)
    try:
        if format == "gif":
            write_gif(clip, str(path))
        else:
            clip.write_videofile(path, logger=None)
    except TypeError:
        try:
            if format == "gif":
                clip.write_gif(path, verbose=False, proggres_bar=False)
            else:
                clip.write_videofile(path, verbose=False, proggres_bar=False)
        except TypeError:
            if format == "gif":
                clip.write_gif(path, verbose=False)
            else:
                clip.write_videofile(path, verbose=False)


@register(Video)
class VideoSequence(MediaSequence[Any, Video]):
    OBJ_TYPE = "videos"
    OBJ_ARTIFACT_TYPE = "videos"

    def __init__(self, items: Sequence[Any]):
        super().__init__(items, Video)

    def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
        super().bind_to_artifact(artifact)
        return {
            "_type": self.OBJ_ARTIFACT_TYPE,
        }

    def to_json(self) -> dict:
        items = [item.to_json() for item in self._items]
        return {
            "_type": self.OBJ_TYPE,
            "count": len(items),
            "videos": items,
            # "captions": [item._caption for item in self._items],
        }
