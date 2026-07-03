"""Runtime hardware scanner for URUK vessel identity.

The scanner is deliberately read-only.  It records what the current runtime
appears to be running on, then derives capability-to-tool expectations that the
self-upgrade engine can diff against TOOL_REGISTRY.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = APP_ROOT / "data"
DEFAULT_PROFILE_PATH = DEFAULT_DATA_DIR / "runtime" / "vessel_profile.json"


@dataclass
class VesselDevice:
    kind: str
    name: str
    id: str = ""
    path: str = ""
    status: str = "present"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VesselProfile:
    schema_version: str
    vessel_id: str
    generated_at: str
    active_probe: bool
    platform: Dict[str, Any]
    hardware: Dict[str, Any]
    devices: List[Dict[str, Any]]
    capabilities: List[str]
    tool_expectations: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


CAPABILITY_TOOL_RULES: List[Dict[str, Any]] = [
    {
        "capability": "sensor.screen",
        "purpose": "screen_capture",
        "accepted_tools": ["capture_screenshot", "screenshot"],
        "suggested_name": "capture_screenshot",
        "category": "screen",
        "priority": "medium",
        "commissioning_required": False,
    },
    {
        "capability": "sensor.screen",
        "purpose": "screen_ocr",
        "accepted_tools": ["ocr_read_screen", "read_screen_text"],
        "suggested_name": "ocr_read_screen",
        "category": "screen",
        "priority": "medium",
        "commissioning_required": False,
    },
    {
        "capability": "sensor.camera",
        "purpose": "camera_frame_capture",
        "accepted_tools": ["capture_camera_frame"],
        "suggested_name": "capture_camera_frame",
        "category": "vision",
        "priority": "medium",
        "commissioning_required": True,
    },
    {
        "capability": "sensor.microphone",
        "purpose": "audio_recording",
        "accepted_tools": ["listen_audio"],
        "suggested_name": "listen_audio",
        "category": "audio",
        "priority": "medium",
        "commissioning_required": False,
    },
    {
        "capability": "sensor.microphone",
        "purpose": "speech_to_text",
        "accepted_tools": ["transcribe_audio"],
        "suggested_name": "transcribe_audio",
        "category": "audio",
        "priority": "medium",
        "commissioning_required": False,
    },
    {
        "capability": "actuator.speaker",
        "purpose": "text_to_speech",
        "accepted_tools": ["speak_text"],
        "suggested_name": "speak_text",
        "category": "audio",
        "priority": "medium",
        "commissioning_required": False,
    },
    {
        "capability": "bus.serial",
        "purpose": "servo_or_motor_control",
        "accepted_tools": ["move_servo", "control_motor"],
        "suggested_name": "move_servo",
        "category": "robotics",
        "priority": "high",
        "commissioning_required": True,
    },
    {
        "capability": "middleware.ros",
        "purpose": "ros_publish",
        "accepted_tools": ["ros_publish"],
        "suggested_name": "ros_publish",
        "category": "robotics",
        "priority": "high",
        "commissioning_required": True,
    },
    {
        "capability": "middleware.ros",
        "purpose": "ros_subscribe",
        "accepted_tools": ["ros_subscribe"],
        "suggested_name": "ros_subscribe",
        "category": "robotics",
        "priority": "high",
        "commissioning_required": True,
    },
    {
        "capability": "sensor.gps",
        "purpose": "location_reading",
        "accepted_tools": ["get_location"],
        "suggested_name": "get_location",
        "category": "location",
        "priority": "high",
        "commissioning_required": True,
    },
]


_PROFILE_CACHE: Optional[VesselProfile] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_vessel_id(parts: Iterable[str]) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _dedupe_devices(devices: List[VesselDevice]) -> List[VesselDevice]:
    seen = set()
    out: List[VesselDevice] = []
    for dev in devices:
        if dev.id.startswith("sounddevice:"):
            key = (dev.kind, dev.name)
        else:
            key = (dev.kind, dev.id or dev.path or dev.name)
        if key in seen:
            continue
        seen.add(key)
        out.append(dev)
    return out


def _safe_ps_json(script: str, timeout: float = 4.0) -> Dict[str, Any]:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return {}
    try:
        cp = subprocess.run(
            [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if cp.returncode != 0 or not cp.stdout.strip():
            return {}
        data = json.loads(cp.stdout)
        return data if isinstance(data, dict) else {}
    except (Exception, KeyboardInterrupt):
        return {}


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _scan_windows_gpu_devices() -> List[VesselDevice]:
    script = (
        "$result=[ordered]@{"
        "VideoControllers=@(Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion)"
        "}; $result | ConvertTo-Json -Depth 4 -Compress"
    )
    data = _safe_ps_json(script, timeout=3.0)
    devices: List[VesselDevice] = []
    for item in _as_list(data.get("VideoControllers")):
        name = str(item.get("Name") or "").strip()
        if name:
            devices.append(VesselDevice(
                kind="gpu",
                name=name,
                id=name,
                metadata={
                    "adapter_ram": item.get("AdapterRAM"),
                    "driver_version": item.get("DriverVersion"),
                },
            ))
    return devices


def _scan_windows_devices() -> List[VesselDevice]:
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$result=[ordered]@{"
        "VideoControllers=@(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion);"
        "Cameras=@(Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue | "
        "Select-Object FriendlyName,InstanceId,Class,Status);"
        "SerialPorts=@(Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name,PNPDeviceID,Description)"
        "}; $result | ConvertTo-Json -Depth 4 -Compress"
    )
    devices: List[VesselDevice] = []
    data: Dict[str, Any] = _safe_ps_json(script, timeout=6.0)
    if os.environ.get("URUK_VESSEL_DEEP_SCAN", "").strip() == "1":
        data.update(_safe_ps_json(
            "$result=[ordered]@{"
            "PortDevices=@(Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue | "
            "Select-Object FriendlyName,InstanceId,Class,Status);"
            "Sensors=@(Get-PnpDevice -Class Sensor -ErrorAction SilentlyContinue | "
            "Select-Object FriendlyName,InstanceId,Class,Status)"
            "}; $result | ConvertTo-Json -Depth 4 -Compress",
            timeout=5.0,
        ))

    for item in _as_list(data.get("VideoControllers")):
        name = str(item.get("Name") or "").strip()
        if name:
            devices.append(VesselDevice(
                kind="gpu",
                name=name,
                id=name,
                metadata={
                    "adapter_ram": item.get("AdapterRAM"),
                    "driver_version": item.get("DriverVersion"),
                },
            ))

    for item in _as_list(data.get("Cameras")):
        name = str(item.get("Name") or item.get("FriendlyName") or "").strip()
        if name:
            devices.append(VesselDevice(
                kind="camera",
                name=name,
                id=str(item.get("DeviceID") or item.get("InstanceId") or name),
                status=str(item.get("Status") or "present"),
                metadata={"pnp_class": item.get("PNPClass") or item.get("Class")},
            ))

    for item in _as_list(data.get("AudioDevices")):
        name = str(item.get("Name") or "").strip()
        if name:
            devices.append(VesselDevice(
                kind="audio_device",
                name=name,
                id=str(item.get("DeviceID") or name),
                status=str(item.get("Status") or "present"),
            ))

    for key in ("SerialPorts", "PortDevices"):
        for item in _as_list(data.get(key)):
            name = str(item.get("Name") or item.get("FriendlyName") or item.get("DeviceID") or "").strip()
            if name:
                devices.append(VesselDevice(
                    kind="serial",
                    name=name,
                    id=str(item.get("PNPDeviceID") or item.get("InstanceId") or item.get("DeviceID") or name),
                    path=str(item.get("DeviceID") or ""),
                    status=str(item.get("Status") or "present"),
                    metadata={
                        "description": item.get("Description"),
                        "source": key,
                        "pnp_class": item.get("Class"),
                    },
                ))

    for item in _as_list(data.get("Sensors")):
        name = str(item.get("Name") or item.get("FriendlyName") or "").strip()
        if not name:
            continue
        kind = "gps" if any(token in name.lower() for token in ("gps", "gnss", "location")) else "sensor"
        devices.append(VesselDevice(
            kind=kind,
            name=name,
            id=str(item.get("DeviceID") or item.get("InstanceId") or name),
            status=str(item.get("Status") or "present"),
            metadata={"pnp_class": item.get("PNPClass") or item.get("Class")},
        ))

    return devices


def _scan_posix_devices() -> List[VesselDevice]:
    devices: List[VesselDevice] = []
    for path in sorted(glob.glob("/dev/video*")):
        devices.append(VesselDevice(kind="camera", name=Path(path).name, path=path, id=path))
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/serial/by-id/*"):
        for path in sorted(glob.glob(pattern)):
            lower = path.lower()
            kind = "gps" if ("gps" in lower or "gnss" in lower) else "serial"
            devices.append(VesselDevice(kind=kind, name=Path(path).name, path=path, id=path))
    for path in sorted(glob.glob("/dev/i2c*")):
        devices.append(VesselDevice(kind="i2c", name=Path(path).name, path=path, id=path))
    return devices


def _scan_sounddevice() -> List[VesselDevice]:
    try:
        import sounddevice as sd  # type: ignore
    except Exception:
        return []
    devices: List[VesselDevice] = []
    try:
        for idx, item in enumerate(sd.query_devices()):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"audio_device_{idx}")
            if int(item.get("max_input_channels") or 0) > 0:
                devices.append(VesselDevice(kind="audio_input", name=name, id=f"sounddevice:{idx}"))
            if int(item.get("max_output_channels") or 0) > 0:
                devices.append(VesselDevice(kind="audio_output", name=name, id=f"sounddevice:{idx}"))
    except Exception:
        return []
    return devices


def _scan_ros() -> List[VesselDevice]:
    devices: List[VesselDevice] = []
    ros_version = os.environ.get("ROS_VERSION") or ""
    ros_distro = os.environ.get("ROS_DISTRO") or ""
    ros_tool = shutil.which("ros2") or shutil.which("rostopic")
    if ros_version or ros_distro or ros_tool:
        metadata = {"ros_version": ros_version, "ros_distro": ros_distro, "tool": ros_tool or ""}
        if ros_tool:
            try:
                cmd = [ros_tool, "topic", "list"] if Path(ros_tool).name.startswith("ros2") else [ros_tool, "list"]
                cp = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
                if cp.returncode == 0:
                    topics = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
                    metadata["topic_count"] = len(topics)
                    metadata["topics_sample"] = topics[:10]
            except Exception:
                metadata["topic_probe"] = "unavailable"
        devices.append(VesselDevice(kind="ros", name=ros_distro or "ros", id=ros_distro or ros_tool or "ros", metadata=metadata))
    return devices


def _probe_camera_opencv() -> Optional[VesselDevice]:
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    try:
        cap = cv2.VideoCapture(0)
        ok = bool(cap is not None and cap.isOpened())
        cap.release()
        if ok:
            return VesselDevice(kind="camera", name="opencv_camera_0", id="cv2:0", metadata={"active_probe": True})
    except Exception:
        return None
    return None


def _hardware_summary(devices: List[VesselDevice]) -> Dict[str, Any]:
    ram_bytes = None
    try:
        import psutil  # type: ignore
        ram_bytes = int(psutil.virtual_memory().total)
    except Exception:
        pass
    gpus = [d for d in devices if d.kind == "gpu"]
    return {
        "cpu_count": os.cpu_count(),
        "cpu": platform.processor() or platform.machine(),
        "ram_bytes": ram_bytes,
        "gpu_count": len(gpus),
        "gpu_names": [g.name for g in gpus[:5]],
    }


def _derive_capabilities(devices: List[VesselDevice]) -> List[str]:
    kinds = {d.kind for d in devices}
    caps = {"compute.local_cpu"}
    if any(k in kinds for k in ("gpu",)):
        caps.add("compute.gpu")
    if platform.system().lower() == "windows" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        caps.add("sensor.screen")
    if "camera" in kinds:
        caps.add("sensor.camera")
    if "audio_input" in kinds:
        caps.add("sensor.microphone")
    if "audio_output" in kinds:
        caps.add("actuator.speaker")
    if "serial" in kinds:
        caps.add("bus.serial")
        caps.add("actuator.motor_control_candidate")
    if "i2c" in kinds:
        caps.add("bus.i2c")
    if "ros" in kinds:
        caps.add("middleware.ros")
    if "gps" in kinds:
        caps.add("sensor.gps")
    return sorted(caps)


def _expectations_for(capabilities: Iterable[str]) -> List[Dict[str, Any]]:
    caps = set(capabilities)
    return [dict(rule) for rule in CAPABILITY_TOOL_RULES if rule["capability"] in caps]


class VesselScanner:
    def __init__(self, *, active_probe: Optional[bool] = None) -> None:
        if active_probe is None:
            active_probe = os.environ.get("URUK_VESSEL_ACTIVE_PROBE", "").strip() == "1"
        self.active_probe = bool(active_probe)

    def scan(self) -> VesselProfile:
        warnings: List[str] = []
        try:
            sys_name = platform.system()
        except (Exception, KeyboardInterrupt):
            sys_name = "Windows"  # safe fallback during hot-reload worker spawn
        devices: List[VesselDevice] = []

        if sys_name.lower() == "windows":
            devices.extend(_scan_windows_devices())
        else:
            devices.extend(_scan_posix_devices())

        devices.extend(_scan_sounddevice())
        devices.extend(_scan_ros())

        if self.active_probe:
            probed = _probe_camera_opencv()
            if probed:
                devices.append(probed)
            else:
                warnings.append("active camera probe requested but no OpenCV camera opened")
        else:
            warnings.append("active camera probe disabled; set URUK_VESSEL_ACTIVE_PROBE=1 to test cv2.VideoCapture(0)")

        devices = _dedupe_devices(devices)
        capabilities = _derive_capabilities(devices)
        hardware = _hardware_summary(devices)
        if hardware.get("ram_bytes"):
            capabilities = sorted(set(capabilities) | {"memory.local_ram"})

        platform_info = {
            "system": sys_name,
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }
        vessel_id = _stable_vessel_id([
            platform.node(),
            sys_name,
            platform.machine(),
            hardware.get("cpu"),
        ])

        return VesselProfile(
            schema_version="vessel_profile.v1",
            vessel_id=vessel_id,
            generated_at=_utc_now(),
            active_probe=self.active_probe,
            platform=platform_info,
            hardware=hardware,
            devices=[asdict(d) for d in devices],
            capabilities=capabilities,
            tool_expectations=_expectations_for(capabilities),
            warnings=warnings,
        )


def profile_path(data_dir: Optional[Path] = None) -> Path:
    base = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    return base / "runtime" / "vessel_profile.json"


def save_vessel_profile(profile: VesselProfile, data_dir: Optional[Path] = None) -> Path:
    path = profile_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_saved_vessel_profile(data_dir: Optional[Path] = None) -> Optional[VesselProfile]:
    path = profile_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return VesselProfile(**data)
    except Exception:
        return None


def _device_count(profile: VesselProfile, kind: str) -> int:
    return sum(1 for dev in profile.devices if isinstance(dev, dict) and dev.get("kind") == kind)


def _completeness_score(profile: VesselProfile) -> int:
    return (
        len(profile.capabilities)
        + int(profile.hardware.get("gpu_count") or 0) * 3
        + _device_count(profile, "camera") * 3
        + _device_count(profile, "serial") * 3
        + _device_count(profile, "gps") * 3
        + _device_count(profile, "ros") * 3
    )


def _prefer_last_known_if_better(current: VesselProfile, data_dir: Optional[Path] = None) -> VesselProfile:
    saved = load_saved_vessel_profile(data_dir)
    if not saved or saved.vessel_id != current.vessel_id:
        return current
    if _completeness_score(saved) <= _completeness_score(current):
        return current

    data = saved.to_dict()
    data["generated_at"] = current.generated_at
    data["active_probe"] = current.active_probe
    data["warnings"] = list(current.warnings or []) + [
        "using last-known hardware details because current scan was less complete",
        f"last_known_generated_at={saved.generated_at}",
    ]
    data["hardware"] = dict(saved.hardware or {})
    data["hardware"]["scan_duration_ms"] = current.hardware.get("scan_duration_ms")
    return VesselProfile(**data)


def get_vessel_profile(*, force: bool = False, data_dir: Optional[Path] = None, save: bool = True) -> VesselProfile:
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None and not force:
        return _PROFILE_CACHE
    started = time.time()
    try:
        profile = VesselScanner().scan()
    except Exception as exc:
        platform_info = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }
        profile = VesselProfile(
            schema_version="vessel_profile.v1",
            vessel_id=_stable_vessel_id([platform.node(), platform.system(), platform.machine()]),
            generated_at=_utc_now(),
            active_probe=False,
            platform=platform_info,
            hardware={"cpu_count": os.cpu_count(), "cpu": platform.processor() or platform.machine()},
            devices=[],
            capabilities=["compute.local_cpu"],
            tool_expectations=[],
            warnings=[f"vessel scan failed: {type(exc).__name__}: {exc}"],
        )
    profile.hardware["scan_duration_ms"] = int((time.time() - started) * 1000)
    profile = _prefer_last_known_if_better(profile, data_dir)
    _PROFILE_CACHE = profile
    if save:
        try:
            save_vessel_profile(profile, data_dir)
        except Exception:
            pass
    return profile


def initialize_vessel_profile(data_dir: Optional[Path] = None) -> VesselProfile:
    return get_vessel_profile(force=True, data_dir=data_dir, save=True)


def identify_hardware_tool_gaps(profile: VesselProfile | Dict[str, Any], tool_names: Iterable[str]) -> List[Dict[str, Any]]:
    data = profile.to_dict() if isinstance(profile, VesselProfile) else dict(profile or {})
    tools = set(tool_names or [])
    capabilities = set(data.get("capabilities") or [])
    devices = data.get("devices") or []
    by_kind: Dict[str, List[str]] = {}
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        by_kind.setdefault(str(dev.get("kind") or "unknown"), []).append(
            str(dev.get("path") or dev.get("name") or dev.get("id") or "device")
        )

    gaps: List[Dict[str, Any]] = []
    for rule in CAPABILITY_TOOL_RULES:
        cap = rule["capability"]
        if cap not in capabilities:
            continue
        accepted = list(rule.get("accepted_tools") or [])
        present = [name for name in accepted if name in tools]
        if present:
            continue
        suggested = str(rule.get("suggested_name") or (accepted[0] if accepted else ""))
        evidence_bits = []
        if cap == "bus.serial":
            evidence_bits.append(f"serial devices: {', '.join(by_kind.get('serial', [])[:5]) or 'present'}")
        elif cap == "middleware.ros":
            evidence_bits.append(f"ROS detected: {', '.join(by_kind.get('ros', [])[:5]) or 'present'}")
        elif cap == "sensor.gps":
            evidence_bits.append(f"GPS/GNSS devices: {', '.join(by_kind.get('gps', [])[:5]) or 'present'}")
        elif cap == "sensor.camera":
            evidence_bits.append(f"camera devices: {', '.join(by_kind.get('camera', [])[:5]) or 'present'}")
        else:
            evidence_bits.append(f"capability detected: {cap}")
        evidence_bits.append(f"missing accepted tools: {', '.join(accepted)}")

        gaps.append({
            "id": f"hardware_gap_{cap.replace('.', '_')}_{rule.get('purpose')}",
            "type": "hardware_gap",
            "category": rule.get("category", "hardware"),
            "hardware_capability": cap,
            "purpose": rule.get("purpose"),
            "suggested_name": suggested,
            "accepted_tools": accepted,
            "present_tools": present,
            "description": f"Hardware capability {cap} is present but no tool handles {rule.get('purpose')}.",
            "evidence": "; ".join(evidence_bits),
            "priority": rule.get("priority", "medium"),
            "commissioning_required": bool(rule.get("commissioning_required")),
            "vessel_id": data.get("vessel_id"),
        })
    return gaps


if __name__ == "__main__":
    print(json.dumps(get_vessel_profile(force=True).to_dict(), ensure_ascii=False, indent=2))
