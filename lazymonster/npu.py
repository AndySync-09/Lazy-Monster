"""Accelerator detection via OpenVINO. The NPU is where always-on models
(wake word, later local speech) belong: tiny power, no CPU load.

`select_device()` is the single place later milestones ask "where do I run?"."""
import time
from typing import Dict, Optional


def devices() -> Dict[str, str]:
    try:
        import openvino as ov
    except Exception:
        return {}
    core = ov.Core()
    out = {}
    for d in core.available_devices:
        try:
            out[d] = core.get_property(d, "FULL_DEVICE_NAME")
        except Exception:
            out[d] = d
    return out


def select_device(preference: str = "auto") -> str:
    avail = devices()
    pref = preference.upper()
    if pref != "AUTO":
        return pref if pref in avail else "CPU"
    for d in ("NPU", "GPU", "CPU"):
        if any(k.startswith(d) for k in avail):
            return next(k for k in avail if k.startswith(d))
    return "CPU"


def probe(device: str, iters: int = 200) -> Optional[dict]:
    """Compile and run a small static-shape model (the kind the NPU needs) and
    time it. Proves the device is usable from this environment."""
    import numpy as np
    import openvino as ov
    import openvino.opset13 as ops
    x = ops.parameter([1, 512], np.float32, name="x")
    h = ops.relu(ops.matmul(x, ops.constant(np.random.rand(512, 512).astype(np.float32) * 0.01), False, False))
    y = ops.matmul(h, ops.constant(np.random.rand(512, 64).astype(np.float32) * 0.01), False, False)
    model = ov.Model([y], [x], "lazymonster_probe")
    t0 = time.perf_counter()
    compiled = ov.Core().compile_model(model, device)
    compile_ms = (time.perf_counter() - t0) * 1000
    req = compiled.create_infer_request()
    inp = np.random.rand(1, 512).astype(np.float32)
    for _ in range(10):
        req.infer({0: inp})
    t0 = time.perf_counter()
    for _ in range(iters):
        req.infer({0: inp})
    per = (time.perf_counter() - t0) / iters * 1000
    return {"device": device, "compile_ms": round(compile_ms, 1), "infer_ms": round(per, 3)}
