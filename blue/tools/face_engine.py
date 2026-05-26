"""
Blue Robot Face Engine (OpenCV SFace + YuNet)
=============================================
Real face recognition with no dlib / no compilation. Uses the face modules
bundled with opencv-python (>=4.5.4):

- YuNet  (FaceDetectorYN)   - detects faces + 5 landmarks
- SFace  (FaceRecognizerSF) - 128-d face embeddings, cosine matching

Models are small ONNX files fetched once from the official OpenCV Zoo into
data/models/ (gitignored). If the models can't be obtained or OpenCV lacks the
face modules, every entry point degrades gracefully to "unavailable" so the
caller can fall back to the older LLM-eyeball approach.

The gallery of known people is built from the reference photos already stored
in visual memory (people.image_path). Embeddings are cached by (path, mtime),
so matching a live frame doesn't recompute enrolled faces every time.
"""

from __future__ import annotations

import os
import threading
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

_MODELS_DIR = os.environ.get("BLUE_FACE_MODELS_DIR", os.path.join("data", "models"))

_YUNET_NAME = "face_detection_yunet_2023mar.onnx"
_SFACE_NAME = "face_recognition_sface_2021dec.onnx"

_YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/"
              "models/face_detection_yunet/" + _YUNET_NAME)
_SFACE_URL = ("https://github.com/opencv/opencv_zoo/raw/main/"
              "models/face_recognition_sface/" + _SFACE_NAME)

# Minimum plausible sizes (bytes) so a truncated/HTML download is rejected.
_YUNET_MIN = 100_000
_SFACE_MIN = 10_000_000

# SFace's reference cosine threshold for "same person" is 0.363. We default a
# touch higher to bias toward "don't guess" on a personal robot with few
# enrolled faces. Override with BLUE_FACE_COSINE.
def _cos_threshold() -> float:
    try:
        return float(os.environ.get("BLUE_FACE_COSINE", "0.40"))
    except ValueError:
        return 0.40


# YuNet detection confidence. 0.7 (the OpenCV sample default) rejects perfectly
# good faces — real enrollment photos commonly score ~0.65. 0.6 reliably catches
# them without the false positives that appear at 0.5. Override BLUE_FACE_DETECT.
def _detect_threshold() -> float:
    try:
        return float(os.environ.get("BLUE_FACE_DETECT", "0.6"))
    except ValueError:
        return 0.6


# Minimum face size (shorter side, px) to attempt recognition. Below this a face
# is too small/distant for a reliable embedding — e.g. a photo held up to the
# camera, or someone across the room — and is reported as "distant" rather than
# matched or guessed. A real 56px face still matched correctly in testing, so
# 40 is conservative; raise via BLUE_FACE_MIN_PX for stricter behavior.
def _min_face_px() -> float:
    try:
        return float(os.environ.get("BLUE_FACE_MIN_PX", "40"))
    except ValueError:
        return 40.0


# Longest-side cap before detection. Huge phone photos (4000px+) are slow and
# less reliable; YuNet works well at moderate sizes. Faces stay well above the
# 112px SFace needs.
_MAX_SIDE = 1600


_lock = threading.Lock()


# --------------------------------------------------------------------------
# Model acquisition
# --------------------------------------------------------------------------

def _download(url: str, dest: str, min_size: int) -> bool:
    tmp = dest + ".part"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        urllib.request.urlretrieve(url, tmp)
        if os.path.getsize(tmp) < min_size:
            os.remove(tmp)
            print(f"[FACE] Downloaded model too small, rejected: {url}")
            return False
        os.replace(tmp, dest)
        print(f"[FACE] Downloaded {os.path.basename(dest)}")
        return True
    except Exception as e:
        print(f"[FACE] Model download failed ({url}): {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def _ensure_model(name: str, url: str, min_size: int) -> Optional[str]:
    path = os.path.join(_MODELS_DIR, name)
    if os.path.exists(path) and os.path.getsize(path) >= min_size:
        return path
    if _download(url, path, min_size):
        return path
    return None


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

class FaceEngine:
    """Detects and embeds faces; matches them against an enrolled gallery."""

    def __init__(self):
        self._cv2 = None
        self._detector = None
        self._recognizer = None
        self._ready: Optional[bool] = None  # tri-state: None=untried
        # gallery: name -> list of (embedding, source_path)
        self._gallery: Dict[str, List[np.ndarray]] = {}
        # cache: source_path -> (mtime, embedding or None)
        self._embed_cache: Dict[str, Tuple[float, Optional[np.ndarray]]] = {}

    # ---- lazy init -------------------------------------------------------

    def _init(self) -> bool:
        """Load OpenCV + models. Returns True if recognition is usable."""
        if self._ready is not None:
            return self._ready
        with _lock:
            if self._ready is not None:
                return self._ready
            self._ready = self._try_init()
            return self._ready

    def _try_init(self) -> bool:
        try:
            import cv2
        except ImportError:
            print("[FACE] OpenCV not installed - face recognition disabled")
            return False
        if not (hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")):
            print("[FACE] OpenCV lacks FaceDetectorYN/FaceRecognizerSF - disabled")
            return False

        yunet = _ensure_model(_YUNET_NAME, _YUNET_URL, _YUNET_MIN)
        sface = _ensure_model(_SFACE_NAME, _SFACE_URL, _SFACE_MIN)
        if not (yunet and sface):
            print("[FACE] Models unavailable - face recognition disabled")
            return False

        try:
            self._cv2 = cv2
            self._detector = cv2.FaceDetectorYN.create(
                yunet, "", (320, 320), _detect_threshold(), 0.3, 5000)
            self._recognizer = cv2.FaceRecognizerSF.create(sface, "")
        except Exception as e:
            print(f"[FACE] Failed to create models: {e}")
            return False
        print("[FACE] OpenCV SFace recognition ready")
        return True

    @property
    def available(self) -> bool:
        return self._init()

    # ---- detection + embedding ------------------------------------------

    def _load_bgr(self, image_path: str):
        """Load an image as a BGR ndarray, applying EXIF orientation and
        downscaling huge images. cv2.imread ignores EXIF, so portrait phone
        photos would otherwise load sideways and detection would miss the face.
        Detection and embedding both use this same array so face coordinates
        stay consistent. Falls back to cv2.imread if Pillow is unavailable."""
        img = None
        try:
            from PIL import Image, ImageOps
            with Image.open(image_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                img = self._cv2.cvtColor(np.array(im), self._cv2.COLOR_RGB2BGR)
        except Exception:
            img = self._cv2.imread(image_path)
        if img is None:
            return None
        h, w = img.shape[:2]
        if max(h, w) > _MAX_SIDE:
            s = _MAX_SIDE / float(max(h, w))
            img = self._cv2.resize(img, (int(w * s), int(h * s)))
        return img

    def _detect(self, img) -> Optional[np.ndarray]:
        """Return YuNet face rows (Nx15) or None."""
        h, w = img.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(img)
        return faces  # None or Nx15

    def _embed(self, img, face_row) -> Optional[np.ndarray]:
        """L2-normalized 128-d embedding for one detected face."""
        try:
            aligned = self._recognizer.alignCrop(img, face_row)
            feat = self._recognizer.feature(aligned).flatten().astype(np.float32)
            norm = np.linalg.norm(feat)
            if norm == 0:
                return None
            return feat / norm
        except Exception as e:
            print(f"[FACE] Embedding failed: {e}")
            return None

    def embed_image(self, image_path: str) -> Optional[np.ndarray]:
        """Embedding of the single largest face in an image (for enrollment).
        Returns None if no usable face is found or recognition is unavailable."""
        if not self._init():
            return None
        img = self._load_bgr(image_path)
        if img is None:
            return None
        faces = self._detect(img)
        if faces is None or len(faces) == 0:
            return None
        # Largest face (w*h) is the enrollment subject.
        best = max(faces, key=lambda r: float(r[2]) * float(r[3]))
        return self._embed(img, best)

    # ---- gallery ---------------------------------------------------------

    def _cached_embedding(self, image_path: str) -> Optional[np.ndarray]:
        try:
            mtime = os.path.getmtime(image_path)
        except OSError:
            return None
        cached = self._embed_cache.get(image_path)
        if cached and cached[0] == mtime:
            return cached[1]
        emb = self.embed_image(image_path)
        self._embed_cache[image_path] = (mtime, emb)
        return emb

    def build_gallery(self, people: List[Dict[str, Any]]) -> int:
        """(Re)build the gallery from people rows that carry an image_path.
        Returns the number of people with a usable enrolled face."""
        gallery: Dict[str, List[np.ndarray]] = {}
        for p in people:
            path = p.get("image_path")
            name = p.get("name")
            if not (path and name and os.path.exists(path)):
                continue
            emb = self._cached_embedding(path)
            if emb is not None:
                gallery.setdefault(name, []).append(emb)
        self._gallery = gallery
        return len(gallery)

    # ---- recognition -----------------------------------------------------

    def identify(self, image_path: str) -> Dict[str, Any]:
        """Identify faces in a probe image against the current gallery.

        Returns:
            {
              "available": bool,          # engine usable
              "faces_detected": int,
              "recognized": [ {"name", "confidence"} ],  # one per matched face
              "unknown_faces": int,       # big enough to judge, but no match
              "distant_faces": int,       # too small/far to reliably identify
            }
        """
        if not self._init():
            return {"available": False, "faces_detected": 0,
                    "recognized": [], "unknown_faces": 0, "distant_faces": 0}

        result = {"available": True, "faces_detected": 0,
                  "recognized": [], "unknown_faces": 0, "distant_faces": 0}

        img = self._load_bgr(image_path)
        if img is None:
            return result
        faces = self._detect(img)
        if faces is None or len(faces) == 0:
            return result
        result["faces_detected"] = len(faces)

        threshold = _cos_threshold()
        min_px = _min_face_px()
        unknown = 0
        distant = 0
        for row in faces:
            # Faces too small to embed reliably (a photo held to the camera, or
            # someone across the room) are reported as distant, never matched —
            # a tiny face produces a noisy embedding that can falsely match.
            if min(float(row[2]), float(row[3])) < min_px:
                distant += 1
                continue
            probe = self._embed(img, row)
            if probe is None:
                unknown += 1
                continue
            best_name, best_score = None, -1.0
            for name, embs in self._gallery.items():
                for e in embs:
                    score = float(np.dot(probe, e))  # cosine (both normalized)
                    if score > best_score:
                        best_score, best_name = score, name
            if best_name is not None and best_score >= threshold:
                result["recognized"].append(
                    {"name": best_name, "confidence": round(best_score, 3)})
            else:
                unknown += 1
        result["unknown_faces"] = unknown
        result["distant_faces"] = distant
        return result


# --------------------------------------------------------------------------
# Global instance + convenience API
# --------------------------------------------------------------------------

_engine: Optional[FaceEngine] = None


def get_face_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        _engine = FaceEngine()
    return _engine


def is_available() -> bool:
    return get_face_engine().available


def enroll_validate(image_path: str) -> Dict[str, Any]:
    """Used at enrollment time: confirm a usable face exists in a reference
    photo. Returns {available, face_found}."""
    eng = get_face_engine()
    if not eng.available:
        return {"available": False, "face_found": False}
    emb = eng.embed_image(image_path)
    # Warm the cache so the first live match doesn't pay for this embedding.
    if emb is not None:
        try:
            eng._embed_cache[image_path] = (os.path.getmtime(image_path), emb)
        except OSError:
            pass
    return {"available": True, "face_found": emb is not None}


def identify_people(image_path: str, people: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the gallery from `people` (visual-memory rows with image_path) and
    identify faces in `image_path`. Single entry point for the capture flow."""
    eng = get_face_engine()
    if not eng.available:
        return {"available": False, "faces_detected": 0,
                "recognized": [], "unknown_faces": 0, "enrolled": 0}
    enrolled = eng.build_gallery(people)
    out = eng.identify(image_path)
    out["enrolled"] = enrolled
    return out


__all__ = [
    "FaceEngine",
    "get_face_engine",
    "is_available",
    "enroll_validate",
    "identify_people",
]
