#!/usr/bin/env python3
"""Replace per-frame thermal normalization with calibrated 20-90 C mapping."""

from pathlib import Path


path = Path("/backend/app/ros_media.py")
text = path.read_text(encoding="utf-8")
import_anchor = "from .stores import MediaStore, SpatialStore\n"
import_replacement = (
    "from .stores import MediaStore, SpatialStore\n"
    "from .thermal import calibrated_thermal_u8\n"
)
old_block = '''            normalized = cv2.normalize(
                raw.astype(np.float32),
                None,
                0,
                255,
                cv2.NORM_MINMAX,
            ).astype(np.uint8)
'''
new_block = '''            normalized = calibrated_thermal_u8(
                raw,
                message.encoding,
            )
'''
if text.count(import_anchor) != 1:
    raise RuntimeError(f"Expected one import anchor, got {text.count(import_anchor)}")
if text.count(old_block) != 1:
    raise RuntimeError(f"Expected one normalization block, got {text.count(old_block)}")
backup = path.with_suffix(path.suffix + ".pre-fixed-thermal-scale")
if not backup.exists():
    backup.write_text(text, encoding="utf-8")
text = text.replace(import_anchor, import_replacement, 1)
text = text.replace(old_block, new_block, 1)
path.write_text(text, encoding="utf-8")
