from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import cv2
import numpy as np
import streamlit as st
from PIL import Image
from skimage.filters import frangi
from skimage.morphology import skeletonize


TARGET_IMAGE = Path("IMG_1260_000045_jpg.rf.e832a11a8a69ad957cf26409c80008c9.jpg")
CLEAN_IMAGE = Path("IMG_1260_000045_jpg.rf.e832a11a8a69ad957cf26409c80008c9_1.jpg")


@dataclass(frozen=True)
class Params:
    ignore_annotation_overlay: bool
    annotation_min_saturation: int
    annotation_dilation: int
    background_blur_kernel: int
    clahe_clip_limit: float
    clahe_tile_grid_size: int
    grout_dark_threshold: int
    vertical_kernel_height: int
    horizontal_kernel_width: int
    grout_dilation: int
    blackhat_kernel_size: int
    enhancement_blur: int
    use_frangi: bool
    crack_response_threshold: int
    min_area: int
    max_area: int
    min_aspect_ratio: float
    max_extent: float
    max_grout_overlap_ratio: float
    closing_kernel_size: int
    closing_iterations: int
    use_skeleton: bool
    show_grout_mask: bool
    show_rejected_candidates: bool
    show_component_boxes: bool


def odd(value: int) -> int:
    value = max(1, int(value))
    return value if value % 2 == 1 else value + 1


def load_image(source: str | BinaryIO) -> np.ndarray:
    if isinstance(source, str):
        bgr = cv2.imread(source, cv2.IMREAD_COLOR)
        if bgr is None:
            raise FileNotFoundError(f"Could not read image: {source}")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    image = Image.open(source).convert("RGB")
    return np.array(image)


def create_annotation_mask(rgb: np.ndarray, params: Params) -> np.ndarray:
    if not params.ignore_annotation_overlay:
        return np.zeros(rgb.shape[:2], dtype=np.uint8)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    pink_hue = ((hue >= 155) & (hue <= 179)) | ((hue >= 0) & (hue <= 8))
    mask = pink_hue & (saturation >= params.annotation_min_saturation) & (value >= 80)
    mask = mask.astype(np.uint8) * 255

    dilation = max(0, params.annotation_dilation)
    if dilation:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilation, dilation))
        mask = cv2.dilate(mask, kernel, iterations=1)

    return mask


def correct_lighting(gray: np.ndarray, params: Params) -> np.ndarray:
    blur_kernel = odd(params.background_blur_kernel)
    background = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
    corrected = cv2.addWeighted(gray, 1.45, background, -0.45, 80)
    corrected = cv2.normalize(corrected, None, 0, 255, cv2.NORM_MINMAX)

    tile_grid = max(2, int(params.clahe_tile_grid_size))
    clahe = cv2.createCLAHE(
        clipLimit=float(params.clahe_clip_limit),
        tileGridSize=(tile_grid, tile_grid),
    )
    return clahe.apply(corrected.astype(np.uint8))


def detect_grout_mask(gray: np.ndarray, params: Params) -> np.ndarray:
    dark = cv2.inRange(gray, 0, params.grout_dark_threshold)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)

    lines = cv2.HoughLinesP(
        dark,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=70,
        maxLineGap=20,
    )
    line_mask = np.zeros_like(gray)
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = abs(np.degrees(np.arctan2(int(y2) - int(y1), int(x2) - int(x1))))
            angle = min(angle, 180 - angle)
            if angle <= 20 or angle >= 70:
                cv2.line(
                    line_mask,
                    (int(x1), int(y1)),
                    (int(x2), int(y2)),
                    255,
                    max(3, params.grout_dilation * 2 - 1),
                )

    if np.count_nonzero(line_mask) > 0:
        grout = cv2.bitwise_and(line_mask, dark)
        grout = cv2.morphologyEx(grout, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=1)
        return cv2.dilate(grout, np.ones((3, 3), np.uint8), iterations=1)

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (3, max(3, params.vertical_kernel_height)),
    )
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(3, params.horizontal_kernel_width), 3),
    )

    vertical = cv2.morphologyEx(dark, cv2.MORPH_OPEN, vertical_kernel)
    horizontal = cv2.morphologyEx(dark, cv2.MORPH_OPEN, horizontal_kernel)
    grout = cv2.bitwise_or(vertical, horizontal)
    grout = cv2.morphologyEx(grout, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    dilation = max(0, params.grout_dilation)
    if dilation:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilation, dilation))
        grout = cv2.dilate(grout, kernel, iterations=1)

    return grout


def enhance_cracks(corrected: np.ndarray, ignore_mask: np.ndarray, params: Params) -> np.ndarray:
    kernel_size = odd(params.blackhat_kernel_size)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    enhanced = cv2.morphologyEx(corrected, cv2.MORPH_BLACKHAT, kernel)

    if params.use_frangi:
        normalized = corrected.astype(np.float32) / 255.0
        vesselness = frangi(1.0 - normalized, sigmas=range(1, 4), black_ridges=False)
        vesselness = np.nan_to_num(vesselness)
        vesselness = cv2.normalize(vesselness, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        enhanced = cv2.addWeighted(enhanced, 0.65, vesselness, 0.35, 0)

    blur = max(0, params.enhancement_blur)
    if blur:
        enhanced = cv2.GaussianBlur(enhanced, (odd(blur * 2 + 1), odd(blur * 2 + 1)), 0)

    enhanced = enhanced.copy()
    enhanced[ignore_mask > 0] = 0
    return enhanced


def threshold_cracks(enhanced: np.ndarray, ignore_mask: np.ndarray, params: Params) -> np.ndarray:
    _, mask = cv2.threshold(
        enhanced,
        params.crack_response_threshold,
        255,
        cv2.THRESH_BINARY,
    )
    mask[ignore_mask > 0] = 0
    return mask


def remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros_like(mask)

    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area >= min_area:
            cleaned[labels == label] = 255

    return cleaned


def clean_crack_mask(mask: np.ndarray, params: Params) -> np.ndarray:
    cleaned = remove_small_components(mask, params.min_area)

    if params.closing_iterations > 0 and params.closing_kernel_size > 1:
        kernel_size = odd(params.closing_kernel_size)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        cleaned = cv2.morphologyEx(
            cleaned,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=params.closing_iterations,
        )
        cleaned = remove_small_components(cleaned, params.min_area)

    if params.use_skeleton:
        cleaned = skeletonize(cleaned > 0).astype(np.uint8) * 255

    return cleaned


def filter_candidates(
    mask: np.ndarray,
    grout_mask: np.ndarray,
    annotation_mask: np.ndarray,
    params: Params,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    accepted = np.zeros_like(mask)
    rejected = np.zeros_like(mask)
    components: list[dict] = []

    for label in range(1, count):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])

        component_mask = labels == label
        bbox_area = max(1, width * height)
        aspect_ratio = max(width, height) / max(1, min(width, height))
        extent = area / bbox_area
        grout_overlap = int(np.count_nonzero(component_mask & (grout_mask > 0))) / max(1, area)
        annotation_overlap = int(np.count_nonzero(component_mask & (annotation_mask > 0))) / max(1, area)

        is_long = aspect_ratio >= params.min_aspect_ratio
        is_curved = area >= params.min_area * 2 and extent <= params.max_extent * 0.40
        keep = (
            params.min_area <= area <= params.max_area
            and (is_long or is_curved)
            and extent <= params.max_extent
            and grout_overlap <= params.max_grout_overlap_ratio
            and annotation_overlap == 0
        )

        target = accepted if keep else rejected
        target[component_mask] = 255
        components.append(
            {
                "accepted": keep,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "area": area,
                "aspect_ratio": aspect_ratio,
                "extent": extent,
                "grout_overlap": grout_overlap,
            }
        )

    return accepted, rejected, components


def make_overlay(
    rgb: np.ndarray,
    final_mask: np.ndarray,
    grout_mask: np.ndarray,
    rejected_mask: np.ndarray,
    params: Params,
    components: list[dict] | None = None,
) -> np.ndarray:
    overlay = rgb.copy()

    if params.show_grout_mask:
        overlay[grout_mask > 0] = (0.55 * overlay[grout_mask > 0] + np.array([20, 95, 230]) * 0.45).astype(np.uint8)

    if params.show_rejected_candidates:
        overlay[rejected_mask > 0] = (0.55 * overlay[rejected_mask > 0] + np.array([230, 45, 45]) * 0.45).astype(np.uint8)

    overlay[final_mask > 0] = (0.35 * overlay[final_mask > 0] + np.array([255, 230, 0]) * 0.65).astype(np.uint8)

    if params.show_component_boxes and components:
        for component in components:
            if not component["accepted"]:
                continue
            x = component["x"]
            y = component["y"]
            w = component["width"]
            h = component["height"]
            cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 255, 255), 1)

    return overlay


def make_crack_annotation(rgb: np.ndarray, components: list[dict]) -> np.ndarray:
    annotated = rgb.copy()
    for component in components:
        if not component["accepted"]:
            continue
        x = component["x"]
        y = component["y"]
        width = component["width"]
        height = component["height"]
        pad = 5
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(annotated.shape[1] - 1, x + width + pad)
        y2 = min(annotated.shape[0] - 1, y + height + pad)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 110, 130), 2)
        label_y = max(0, y1 - 28)
        cv2.rectangle(annotated, (x1, label_y), (min(x1 + 66, annotated.shape[1] - 1), y1), (255, 110, 130), -1)
        cv2.putText(
            annotated,
            "crack",
            (x1 + 8, max(17, y1 - 9)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return annotated


def image_to_jpeg_bytes(rgb: np.ndarray) -> bytes:
    buffer = BytesIO()
    Image.fromarray(rgb).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def sidebar_params() -> Params:
    st.sidebar.header("Parameters")

    st.sidebar.subheader("Annotation mask")
    ignore_annotation_overlay = st.sidebar.checkbox("Ignore pink annotation overlay", value=True)
    annotation_min_saturation = st.sidebar.slider("Annotation min saturation", 0, 255, 80)
    annotation_dilation = st.sidebar.slider("Annotation dilation", 0, 15, 5)

    st.sidebar.subheader("Image correction")
    background_blur_kernel = st.sidebar.slider("Background blur kernel", 15, 101, 41, step=2)
    clahe_clip_limit = st.sidebar.slider("CLAHE clip limit", 1.0, 5.0, 2.0, step=0.1)
    clahe_tile_grid_size = st.sidebar.slider("CLAHE tile grid size", 2, 16, 8)

    st.sidebar.subheader("Grout detection")
    grout_dark_threshold = st.sidebar.slider("Grout dark threshold", 20, 120, 70)
    vertical_kernel_height = st.sidebar.slider("Vertical kernel height", 10, 80, 35)
    horizontal_kernel_width = st.sidebar.slider("Horizontal kernel width", 10, 80, 35)
    grout_dilation = st.sidebar.slider("Grout dilation", 1, 15, 5)

    st.sidebar.subheader("Crack enhancement")
    blackhat_kernel_size = st.sidebar.slider("Black-hat kernel size", 3, 31, 9, step=2)
    enhancement_blur = st.sidebar.slider("Enhancement blur", 0, 5, 1)
    use_frangi = st.sidebar.checkbox("Blend Frangi thin-line response", value=False)
    crack_response_threshold = st.sidebar.slider("Crack response threshold", 0, 120, 35)

    st.sidebar.subheader("Cleanup and shape filter")
    min_area = st.sidebar.slider("Minimum area", 1, 500, 120)
    max_area = st.sidebar.slider("Maximum area", 50, 6000, 3000)
    min_aspect_ratio = st.sidebar.slider("Minimum aspect ratio", 1.0, 10.0, 2.5, step=0.1)
    max_extent = st.sidebar.slider("Maximum extent", 0.05, 1.0, 0.50, step=0.05)
    max_grout_overlap_ratio = st.sidebar.slider("Maximum grout overlap", 0.0, 1.0, 0.10, step=0.01)
    closing_kernel_size = st.sidebar.slider("Closing kernel size", 1, 15, 3, step=2)
    closing_iterations = st.sidebar.slider("Closing iterations", 0, 3, 1)
    use_skeleton = st.sidebar.checkbox("Skeletonize cleaned mask", value=False)

    st.sidebar.subheader("Overlay")
    show_grout_mask = st.sidebar.checkbox("Show grout mask", value=True)
    show_rejected_candidates = st.sidebar.checkbox("Show rejected candidates", value=False)
    show_component_boxes = st.sidebar.checkbox("Show component boxes", value=True)

    return Params(
        ignore_annotation_overlay=ignore_annotation_overlay,
        annotation_min_saturation=annotation_min_saturation,
        annotation_dilation=annotation_dilation,
        background_blur_kernel=background_blur_kernel,
        clahe_clip_limit=clahe_clip_limit,
        clahe_tile_grid_size=clahe_tile_grid_size,
        grout_dark_threshold=grout_dark_threshold,
        vertical_kernel_height=vertical_kernel_height,
        horizontal_kernel_width=horizontal_kernel_width,
        grout_dilation=grout_dilation,
        blackhat_kernel_size=blackhat_kernel_size,
        enhancement_blur=enhancement_blur,
        use_frangi=use_frangi,
        crack_response_threshold=crack_response_threshold,
        min_area=min_area,
        max_area=max_area,
        min_aspect_ratio=min_aspect_ratio,
        max_extent=max_extent,
        max_grout_overlap_ratio=max_grout_overlap_ratio,
        closing_kernel_size=closing_kernel_size,
        closing_iterations=closing_iterations,
        use_skeleton=use_skeleton,
        show_grout_mask=show_grout_mask,
        show_rejected_candidates=show_rejected_candidates,
        show_component_boxes=show_component_boxes,
    )


def select_image() -> np.ndarray:
    options = {
        "Clean alternate": CLEAN_IMAGE,
        "Annotated target": TARGET_IMAGE,
    }
    selected = st.selectbox("Image", list(options), index=0)
    upload = st.file_uploader("Upload another tile image", type=["jpg", "jpeg", "png"])

    if upload is not None:
        return load_image(upload)

    return load_image(str(options[selected]))


def show_metric_row(components: list[dict], final_mask: np.ndarray, grout_mask: np.ndarray) -> None:
    accepted = sum(1 for component in components if component["accepted"])
    rejected = len(components) - accepted
    crack_pixels = int(np.count_nonzero(final_mask))
    grout_pixels = int(np.count_nonzero(grout_mask))
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Accepted", accepted)
    col2.metric("Rejected", rejected)
    col3.metric("Crack pixels", crack_pixels)
    col4.metric("Grout pixels", grout_pixels)


def run_pipeline(rgb: np.ndarray, params: Params) -> dict[str, np.ndarray | list[dict]]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    annotation_mask = create_annotation_mask(rgb, params)
    corrected = correct_lighting(gray, params)
    grout_mask = detect_grout_mask(gray, params)
    ignore_mask = cv2.bitwise_or(grout_mask, annotation_mask)
    enhanced = enhance_cracks(corrected, ignore_mask, params)
    raw_mask = threshold_cracks(enhanced, ignore_mask, params)
    cleaned_mask = clean_crack_mask(raw_mask, params)
    final_mask, rejected_mask, components = filter_candidates(
        cleaned_mask,
        grout_mask,
        annotation_mask,
        params,
    )
    overlay = make_overlay(rgb, final_mask, grout_mask, rejected_mask, params, components)
    annotation = make_crack_annotation(rgb, components)

    return {
        "gray": gray,
        "annotation_mask": annotation_mask,
        "corrected": corrected,
        "grout_mask": grout_mask,
        "ignore_mask": ignore_mask,
        "enhanced": enhanced,
        "raw_mask": raw_mask,
        "cleaned_mask": cleaned_mask,
        "final_mask": final_mask,
        "rejected_mask": rejected_mask,
        "components": components,
        "overlay": overlay,
        "annotation": annotation,
    }


def main() -> None:
    st.set_page_config(page_title="Ceramic Tile Crack Detection", layout="wide")
    st.title("Ceramic Tile Crack Detection")

    params = sidebar_params()
    rgb = select_image()
    results = run_pipeline(rgb, params)
    components = results["components"]

    show_metric_row(components, results["final_mask"], results["grout_mask"])

    tabs = st.tabs(
        [
            "Original",
            "Corrected grayscale",
            "Grout mask",
            "Crack enhancement",
            "Raw crack mask",
            "Cleaned crack mask",
            "Final overlay",
            "Crack annotation",
        ]
    )

    with tabs[0]:
        left, right = st.columns(2)
        left.image(rgb, caption="Original", width="stretch")
        right.image(results["annotation_mask"], caption="Annotation exclusion mask", width="stretch")

    with tabs[1]:
        left, right = st.columns(2)
        left.image(results["gray"], caption="Grayscale", clamp=True, width="stretch")
        right.image(results["corrected"], caption="Corrected grayscale", clamp=True, width="stretch")

    with tabs[2]:
        left, right = st.columns(2)
        left.image(results["grout_mask"], caption="Detected grout mask", clamp=True, width="stretch")
        right.image(results["ignore_mask"], caption="Combined ignore mask", clamp=True, width="stretch")

    with tabs[3]:
        st.image(results["enhanced"], caption="Thin dark line enhancement", clamp=True, width="stretch")

    with tabs[4]:
        st.image(results["raw_mask"], caption="Raw crack candidates", clamp=True, width="stretch")

    with tabs[5]:
        left, right = st.columns(2)
        left.image(results["cleaned_mask"], caption="Cleaned candidates", clamp=True, width="stretch")
        right.image(results["rejected_mask"], caption="Rejected candidates", clamp=True, width="stretch")

    with tabs[6]:
        st.image(results["overlay"], caption="Final overlay", width="stretch")
        st.dataframe(
            components,
            width="stretch",
            hide_index=True,
            column_config={
                "accepted": st.column_config.CheckboxColumn("Accepted"),
                "aspect_ratio": st.column_config.NumberColumn("Aspect ratio", format="%.2f"),
                "extent": st.column_config.NumberColumn("Extent", format="%.2f"),
                "grout_overlap": st.column_config.NumberColumn("Grout overlap", format="%.2f"),
            },
        )

    with tabs[7]:
        st.image(results["annotation"], caption="Crack-only annotation output", width="stretch")
        st.download_button(
            "Download crack-only JPG",
            data=image_to_jpeg_bytes(results["annotation"]),
            file_name=TARGET_IMAGE.name,
            mime="image/jpeg",
        )


if __name__ == "__main__":
    main()
