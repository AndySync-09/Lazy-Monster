"""Which machine are we on. One place, so platform branches stay readable."""
import os
import platform
import sys

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
IS_INTEL_MAC = IS_MAC and not IS_APPLE_SILICON


def describe() -> str:
    if IS_APPLE_SILICON:
        return "macOS (Apple Silicon)"
    if IS_INTEL_MAC:
        return "macOS (Intel)"
    if IS_WIN:
        return "Windows"
    return sys.platform
