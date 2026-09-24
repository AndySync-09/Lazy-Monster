"""What the PC is doing right now: CPU, memory, GPU, disk, battery, and what's using them.
Read directly (psutil and Windows performance counters), no Task Manager needed."""
import json
import os
import subprocess
import time
from typing import Optional

_GPU_PS = r"""
$u = (Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples
$c = (Get-Counter '\GPU Engine(*engtype_Compute)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples
$m = (Get-Counter '\GPU Adapter Memory(*)\Shared Usage' -ErrorAction SilentlyContinue).CounterSamples
[pscustomobject]@{
  gpu3d = [math]::Round((($u | Measure-Object CookedValue -Sum).Sum), 1)
  compute = [math]::Round((($c | Measure-Object CookedValue -Sum).Sum), 1)
  shared_gb = [math]::Round((($m | Measure-Object CookedValue -Sum).Sum) / 1GB, 1)
} | ConvertTo-Json -Compress
"""


def gpu() -> Optional[dict]:
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _GPU_PS], capture_output=True, text=True,
                           timeout=8, creationflags=0x08000000)
        return json.loads(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def snapshot(top: int = 6) -> dict:
    import psutil
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)                          # prime per-process CPU counters
        except Exception:
            pass
    cpu = psutil.cpu_percent(interval=1.0)
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["name"] or "?", p.cpu_percent(None) / max(1, psutil.cpu_count()),
                          (p.info["memory_info"].rss if p.info["memory_info"] else 0) / 1e9))
        except Exception:
            continue
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/")
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    by_cpu = sorted(procs, key=lambda x: -x[1])[:top]
    by_ram = sorted(procs, key=lambda x: -x[2])[:top]
    return {"cpu_percent": round(cpu, 1), "cpu_cores": psutil.cpu_count(),
            "ram_used_gb": round(vm.used / 1e9, 1), "ram_total_gb": round(vm.total / 1e9, 1), "ram_percent": vm.percent,
            "disk_free_gb": round(disk.free / 1e9, 1), "disk_percent": disk.percent,
            "battery": None if bat is None else {"percent": round(bat.percent), "plugged_in": bat.power_plugged},
            "gpu": gpu(),
            "top_cpu": [{"name": n, "cpu": round(c, 1)} for n, c, _ in by_cpu if c > 0.5],
            "top_ram": [{"name": n, "gb": round(g, 2)} for n, _, g in by_ram],
            "at": time.strftime("%H:%M:%S")}


def describe(s: dict) -> str:
    """One compact paragraph the brain (or the monster, with no brain) can answer from."""
    parts = [f"CPU {s['cpu_percent']}% across {s['cpu_cores']} threads.",
             f"Memory {s['ram_used_gb']} of {s['ram_total_gb']} GB used ({s['ram_percent']}%).",
             f"Disk {s['disk_free_gb']} GB free."]
    g = s.get("gpu")
    if g:
        parts.append(f"GPU {g['gpu3d']}% busy (compute {g['compute']}%), shared GPU memory in use {g['shared_gb']} GB.")
    if s.get("battery"):
        b = s["battery"]
        parts.append(f"Battery {b['percent']}%{' charging' if b['plugged_in'] else ''}.")
    if s["top_cpu"]:
        parts.append("Busiest: " + ", ".join(f"{p['name']} {p['cpu']}%" for p in s["top_cpu"][:4]) + ".")
    parts.append("Most memory: " + ", ".join(f"{p['name']} {p['gb']} GB" for p in s["top_ram"][:4]) + ".")
    hints = []
    if s["ram_percent"] >= 90:
        hints.append("memory is nearly full, which slows everything down")
    if g and s["ram_total_gb"] and g["shared_gb"] >= 0.6 * s["ram_total_gb"]:
        hints.append("most of the memory is held by the GPU, often a local AI model server (llama-server, Ollama)")
    if s["cpu_percent"] >= 85:
        hints.append("the CPU is maxed out")
    if hints:
        parts.append("Notable: " + "; ".join(hints) + ".")
    return " ".join(parts)


def quick_answer(s: dict) -> str:
    """Spoken summary when there's no brain."""
    t = f"CPU is at {round(s['cpu_percent'])} percent and memory at {round(s['ram_percent'])} percent."
    if s["top_ram"]:
        t += f" {s['top_ram'][0]['name']} uses the most memory."
    if s["ram_percent"] >= 90:
        t += " Memory is nearly full."
    return t
