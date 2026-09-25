"""Reading text in pictures of the screen, on this PC: PP-OCRv4 (via RapidOCR).

The two neural networks (find text, read text) run through OpenVINO at fixed shapes
so they fit the Intel NPU; if the NPU refuses them they run on the GPU or CPU.
Nothing leaves the machine. Used when a window's text can't be read directly
(images, PDFs shown as pictures, remote desktops, games, error dialogs drawn as graphics)."""
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

DET_SIDE, REC_H, REC_W = 960, 48, 960


class _Static:
    """An OpenVINO model compiled at one fixed input shape, fed by padding and read back
    by cropping, so the NPU (which needs fixed shapes) can run it."""

    def __init__(self, core, path: Path, shape, devices, kind: str, fallback):
        m = core.read_model(str(path))
        m.reshape({m.inputs[0]: list(shape)})
        self.kind, self.shape, self.fallback, self.device, self.errors = kind, shape, fallback, None, {}
        for d in devices:
            try:
                self.req = core.compile_model(m, d).create_infer_request()
                self.device = d
                break
            except Exception as e:
                self.errors[d] = f"{type(e).__name__}: {str(e).splitlines()[0][:100]}"
        if self.device is None:
            raise RuntimeError(f"{kind} model could not compile: {self.errors}")

    def __call__(self, x: np.ndarray):
        if self.kind == "det":
            _, _, h, w = x.shape
            if h > self.shape[2] or w > self.shape[3]:
                return self.fallback(x)
            pad = np.zeros(self.shape, dtype=np.float32)
            pad[:, :, :h, :w] = x
            out = list(self.req.infer({0: pad}).values())[0]
            return [out[:, :, :h, :w]]
        b, _, h, w = x.shape                                       # recognition: one line at a time
        if w > self.shape[3]:
            return self.fallback(x)
        outs = []
        for i in range(b):
            pad = np.zeros(self.shape, dtype=np.float32)
            pad[0, :, :h, :w] = x[i]
            out = list(self.req.infer({0: pad}).values())[0]
            steps = max(1, int(round(out.shape[1] * w / self.shape[3])))
            outs.append(out[:, :steps])
        return [np.concatenate(outs, axis=0)]


class ScreenOCR:
    def __init__(self, device: str = "auto"):
        from rapidocr_onnxruntime import RapidOCR
        import rapidocr_onnxruntime as ro
        self.engine = RapidOCR()
        self.device, self.errors = "CPU (ONNX Runtime)", {}
        try:
            import openvino as ov
            from . import npu
        except Exception:
            return
        models = Path(ro.__file__).parent / "models"
        avail = npu.devices()
        order = (["NPU", "GPU", "CPU"] if device == "auto" else [device.upper(), "CPU"])
        order = [d for d in order if d == "CPU" or any(k.startswith(d) for k in avail)]
        core = ov.Core()
        det, rec = self.engine.text_det, self.engine.text_rec
        try:
            det.infer = _Static(core, models / "ch_PP-OCRv4_det_infer.onnx", (1, 3, DET_SIDE, DET_SIDE), order, "det", det.infer)
            rec.session = _Static(core, models / "ch_PP-OCRv4_rec_infer.onnx", (1, 3, REC_H, REC_W), order, "rec", rec.session)
            self.device = f"{det.infer.device} (find) + {rec.session.device} (read)"
            self.errors = {**det.infer.errors, **rec.session.errors}
        except Exception as e:
            self.errors["openvino"] = str(e)[:200]

    def read(self, image) -> List[str]:
        """Lines of text, top to bottom. image: PIL image or numpy RGB array."""
        arr = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
        result, _ = self.engine(arr[:, :, ::-1].copy())          # RapidOCR wants BGR
        if not result:
            return []
        rows = sorted(result, key=lambda r: (round(min(p[1] for p in r[0]) / 12), min(p[0] for p in r[0])))
        return [r[1] for r in rows if float(r[2]) >= 0.5]

    def read_text(self, image) -> str:
        return "\n".join(self.read(image))


_ocr: Optional[ScreenOCR] = None


class VisionOCR:
    """macOS: Apple's Vision framework (VNRecognizeTextRequest). Built into the OS, no download,
    and Apple runs it on the Neural Engine where the Mac has one."""

    def __init__(self, device: str = "auto"):
        import Vision  # noqa: F401  (pyobjc-framework-Vision)
        self.device, self.errors = "Apple Vision (Neural Engine)", {}

    def read(self, image) -> List[str]:
        import io
        import Quartz
        import Vision
        from Foundation import NSData
        buf = io.BytesIO()
        (image if hasattr(image, "save") else __import__("PIL.Image", fromlist=["Image"]).fromarray(image)).save(buf, "PNG")
        raw = buf.getvalue()
        src = Quartz.CGImageSourceCreateWithData(NSData.dataWithBytes_length_(raw, len(raw)), None)
        cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(True)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
        handler.performRequests_error_([req], None)
        rows = []
        for obs in req.results() or []:
            cand = obs.topCandidates_(1)
            if cand and float(cand[0].confidence()) >= 0.4:
                box = obs.boundingBox()
                rows.append((-round(box.origin.y, 2), box.origin.x, str(cand[0].string())))
        return [t for _, _, t in sorted(rows)]

    def read_text(self, image) -> str:
        return "\n".join(self.read(image))


def get(device: str = "auto"):
    global _ocr
    if _ocr is None:
        import sys
        try:
            _ocr = VisionOCR(device) if sys.platform == "darwin" else ScreenOCR(device)
        except Exception:
            _ocr = None
    return _ocr


def bench(image, device: str = "auto") -> dict:
    import sys
    t0 = time.perf_counter()
    o = VisionOCR(device) if sys.platform == "darwin" else ScreenOCR(device)
    load = time.perf_counter() - t0
    o.read(image)                                                # warm-up
    t1 = time.perf_counter()
    lines = o.read(image)
    return {"device": o.device, "load_s": round(load, 1), "read_ms": round((time.perf_counter() - t1) * 1000),
            "lines": len(lines), "errors": o.errors, "sample": lines[:5]}
