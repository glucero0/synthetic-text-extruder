"""ffmpeg-backed video filters, trim/split, and concat for Viewer Edit."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_FILTERS: dict[str, Any] = {
    "brightness": 0,
    "contrast": 0,
    "grayscale": False,
    "sharpen": False,
    "saturation": 100,
    "hueRotate": 0,
    "invert": 0,
    "sepia": 0,
    "blur": 0,
    "exposure": 0,
    "gamma": 1,
    "vignette": 0,
    "tintRed": 0,
    "tintGreen": 0,
    "tintBlue": 0,
}

# Common Windows install locations when ffmpeg is not on PATH.
_WIN_FFMPEG_CANDIDATES = (
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\ffmpeg.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
    os.path.expandvars(r"%USERPROFILE%\scoop\shims\ffmpeg.exe"),
    os.path.expandvars(r"%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffmpeg.exe"),
    os.path.expandvars(r"%ProgramFiles%\Gyan\ffmpeg\bin\ffmpeg.exe"),
)


def _winget_package_ffmpeg_bins() -> tuple[str, ...]:
    """Locate ffmpeg.exe under WinGet package folders (Gyan builds, etc.)."""
    root = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"))
    if not root.is_dir():
        return ()
    found: list[str] = []
    try:
        for path in root.glob("*FFmpeg*/**/bin/ffmpeg.exe"):
            if path.is_file():
                found.append(str(path))
    except OSError:
        return ()
    # Newest package path last alphabetically often wins; sort for stability.
    found.sort()
    return tuple(found)


def _windows_ffmpeg_search_paths() -> tuple[str, ...]:
    return _WIN_FFMPEG_CANDIDATES + _winget_package_ffmpeg_bins()


class FfmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe cannot be located."""


def _candidate_paths(name: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Ordered unique existing paths for a tool (PATH first, then extras)."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: str | None) -> None:
        if not raw:
            return
        try:
            resolved = str(Path(raw).resolve())
        except OSError:
            resolved = os.path.normpath(raw)
        key = resolved.lower()
        if key in seen:
            return
        if not Path(resolved).is_file():
            return
        seen.add(key)
        out.append(resolved)

    _add(shutil.which(name))
    for raw in extra:
        _add(raw)
    return out


def _is_python_scripts_stub(path: str) -> bool:
    low = path.lower().replace("/", "\\")
    return "\\python" in low and "\\scripts\\" in low


def _ffmpeg_version_line(path: str) -> str:
    try:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": 15,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run([path, "-version"], **kwargs)
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    except Exception:  # noqa: BLE001
        logger.debug("Could not read ffmpeg version from %s", path, exc_info=True)
    return ""


def _ffmpeg_looks_modern(path: str, version_line: str | None = None) -> bool:
    """
    Prefer builds new enough for Video Edit filtergraphs.

    Skips tiny Python Scripts stubs that ship ancient (e.g. 2013) binaries which
    reject options like -hide_banner and lack modern scale/pad flags.
    """
    line = version_line if version_line is not None else _ffmpeg_version_line(path)
    if not line:
        return False
    m = re.search(r"ffmpeg version (\d+)\.", line, re.I)
    if m:
        return int(m.group(1)) >= 4
    m = re.search(r"ffmpeg version n-(\d+)", line, re.I)
    if m:
        # Nightlies: N-55702 ≈ 2013; require a much newer git rev.
        return int(m.group(1)) >= 90000
    # Unknown banner — accept only if the binary is a full-sized build.
    try:
        return Path(path).stat().st_size >= 1_000_000
    except OSError:
        return False


def find_ffmpeg() -> str | None:
    extras = (
        _windows_ffmpeg_search_paths() if os.name == "nt" else _WIN_FFMPEG_CANDIDATES
    )
    candidates = _candidate_paths("ffmpeg", extras)
    if not candidates:
        return None
    modern = [p for p in candidates if _ffmpeg_looks_modern(p)]
    if modern:
        # Prefer full installs over ancient Python\\Scripts stubs still on PATH.
        preferred = [p for p in modern if not _is_python_scripts_stub(p)]
        return preferred[0] if preferred else modern[0]
    # Fall back to whatever we found (may still fail modern filtergraphs).
    return candidates[0]


def find_ffprobe() -> str | None:
    ffmpeg = find_ffmpeg()
    extras: list[str] = []
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        extras.append(str(sibling))
    win_paths = (
        _windows_ffmpeg_search_paths() if os.name == "nt" else _WIN_FFMPEG_CANDIDATES
    )
    extras.extend(
        c.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
        for c in win_paths
    )
    candidates = _candidate_paths("ffprobe", tuple(extras))
    if not candidates:
        return None
    if ffmpeg:
        # Prefer ffprobe next to the ffmpeg we selected.
        for path in candidates:
            if Path(path).parent == Path(ffmpeg).parent:
                return path
    return candidates[0]


def ffmpeg_available() -> dict[str, Any]:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return {
            "ok": False,
            "error": (
                "ffmpeg not found. Install a current ffmpeg build "
                "(https://ffmpeg.org/ or `winget install ffmpeg`) and ensure it is on PATH."
            ),
        }
    version = _ffmpeg_version_line(ffmpeg)
    if not _ffmpeg_looks_modern(ffmpeg, version):
        return {
            "ok": False,
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "version": version,
            "error": (
                "ffmpeg is too old for Video Editor"
                + (f" ({version})" if version else "")
                + ". Install a current build from https://ffmpeg.org/ "
                "or `winget install ffmpeg`, and remove outdated copies "
                "(for example under Python\\Scripts)."
            ),
        }
    return {
        "ok": True,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "version": version,
    }


def extract_video_frame_png(
    source: str | Path,
    *,
    at_seconds: float = 0.0,
) -> bytes:
    """Grab a single PNG frame from a video via ffmpeg (for media-basis I2V)."""
    import tempfile

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FfmpegNotFoundError(
            "ffmpeg not found — needed to use a video as Studio basis for generation."
        )
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {src}")
    t = max(0.0, float(at_seconds or 0.0))
    with tempfile.TemporaryDirectory(prefix="rgc_frame_") as tmp:
        out = Path(tmp) / "frame.png"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-y",
            str(out),
        ]
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": 60,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0 or not out.is_file():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                "Could not extract a frame from the basis video"
                + (f": {detail}" if detail else ".")
            )
        return out.read_bytes()


def video_has_audio_stream(source: str | Path) -> bool:
    """True if ffprobe reports at least one audio stream."""
    ffprobe = _require_ffprobe()
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {src}")
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(src),
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "ffprobe failed while checking audio streams")
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return bool(lines)


def extract_audio_mp3(
    source: str | Path,
    *,
    max_seconds: float | None = 600.0,
) -> bytes:
    """Demux audio to a compact mono MP3 for speech transcription."""
    import tempfile

    ffmpeg = _require_ffmpeg()
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {src}")
    with tempfile.TemporaryDirectory(prefix="rgc_audio_") as tmp:
        out = Path(tmp) / "audio.mp3"
        cmd = [ffmpeg, *_ffmpeg_quiet_args(), "-i", str(src)]
        if max_seconds is not None and float(max_seconds) > 0:
            cmd.extend(["-t", f"{float(max_seconds):.3f}"])
        cmd.extend(
            [
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "64k",
                "-y",
                str(out),
            ]
        )
        proc = _run(cmd, timeout=300)
        if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 32:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                "Could not extract audio from video"
                + (f": {detail}" if detail else ".")
            )
        return out.read_bytes()


def extract_video_clip_bytes(
    source: str | Path,
    *,
    max_seconds: float = 90.0,
) -> bytes:
    """Re-encode a short MP4 clip for multimodal fallback when audio is missing."""
    import tempfile

    ffmpeg = _require_ffmpeg()
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {src}")
    dur = max(1.0, float(max_seconds or 90.0))
    with tempfile.TemporaryDirectory(prefix="rgc_clip_") as tmp:
        out = Path(tmp) / "clip.mp4"
        cmd = [
            ffmpeg,
            *_ffmpeg_quiet_args(),
            "-i",
            str(src),
            "-t",
            f"{dur:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-an",
            "-movflags",
            "+faststart",
            "-y",
            str(out),
        ]
        proc = _run(cmd, timeout=300)
        if proc.returncode != 0 or not out.is_file():
            # Copy first N seconds without re-encode as a fallback.
            cmd2 = [
                ffmpeg,
                *_ffmpeg_quiet_args(),
                "-i",
                str(src),
                "-t",
                f"{dur:.3f}",
                "-c",
                "copy",
                "-an",
                "-y",
                str(out),
            ]
            proc2 = _run(cmd2, timeout=120)
            if proc2.returncode != 0 or not out.is_file():
                detail = (proc.stderr or proc2.stderr or "").strip()
                raise RuntimeError(
                    "Could not prepare a short video clip"
                    + (f": {detail}" if detail else ".")
                )
        return out.read_bytes()


def _ffmpeg_quiet_args() -> list[str]:
    """Global quiet flags compatible with older and newer ffmpeg."""
    # Avoid -hide_banner: missing on ancient builds (e.g. 2013 Python Scripts stubs).
    return ["-loglevel", "error"]


def _run(cmd: list[str], *, timeout: float | None = 600) -> subprocess.CompletedProcess[str]:
    logger.info("Running: %s", " ".join(cmd))
    try:
        kwargs: dict[str, Any] = {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out: {cmd[0]}") from exc
    except FileNotFoundError as exc:
        raise FfmpegNotFoundError(str(exc)) from exc


def _require_ffmpeg() -> str:
    status = ffmpeg_available()
    if not status.get("ok"):
        raise FfmpegNotFoundError(
            str(status.get("error") or "ffmpeg not found or not usable.")
        )
    path = status.get("ffmpeg") or find_ffmpeg()
    if not path:
        raise FfmpegNotFoundError(
            "ffmpeg not found. Install ffmpeg and ensure it is on PATH."
        )
    return str(path)


def _require_ffprobe() -> str:
    path = find_ffprobe()
    if not path:
        raise FfmpegNotFoundError(
            "ffprobe not found. Install ffmpeg (includes ffprobe) and ensure it is on PATH."
        )
    return path


def probe_duration(path: str | Path) -> float:
    """Return media duration in seconds."""
    ffprobe = _require_ffprobe()
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {src}")
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(src),
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Could not determine video duration")
    return duration


def probe_video_info(path: str | Path) -> dict[str, Any]:
    ffprobe = _require_ffprobe()
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {src}")
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name:format=duration,size",
            "-of",
            "json",
            str(src),
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    duration = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or src.stat().st_size)
    return {
        "duration": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": stream.get("codec_name") or "",
        "size": size,
    }


def normalize_filters(settings: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, default in DEFAULT_FILTERS.items():
        val = default if settings is None or key not in settings else settings[key]
        if isinstance(default, bool):
            out[key] = bool(val)
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                out[key] = int(float(val))
            except (TypeError, ValueError):
                out[key] = default
        else:
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                out[key] = default
    return out


def has_active_filters(settings: dict[str, Any] | None) -> bool:
    s = normalize_filters(settings)
    return (
        s["brightness"] != 0
        or s["contrast"] != 0
        or s["grayscale"]
        or s["sharpen"]
        or s["saturation"] != 100
        or s["hueRotate"] != 0
        or s["invert"] != 0
        or s["sepia"] != 0
        or s["blur"] != 0
        or s["exposure"] != 0
        or abs(s["gamma"] - 1.0) > 1e-6
        or s["vignette"] != 0
        or s["tintRed"] != 0
        or s["tintGreen"] != 0
        or s["tintBlue"] != 0
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def build_filtergraph(
    filters: dict[str, Any] | None = None,
    *,
    crop: dict[str, Any] | None = None,
    rotation: float = 0,
    source_width: int = 0,
    source_height: int = 0,
) -> str:
    """Build an ffmpeg -vf filtergraph string (may be empty)."""
    parts: list[str] = []
    s = normalize_filters(filters)

    if crop and float(crop.get("w") or 0) > 0 and float(crop.get("h") or 0) > 0:
        cx_f = float(crop.get("x") or 0)
        cy_f = float(crop.get("y") or 0)
        cw_f = float(crop.get("w") or 0)
        ch_f = float(crop.get("h") or 0)
        normalized = bool(crop.get("normalized")) or (
            cw_f <= 1.0 and ch_f <= 1.0 and source_width > 0 and source_height > 0
        )
        if normalized and source_width > 0 and source_height > 0:
            sw, sh = source_width, source_height
            cx = int(_clamp(cx_f * sw, 0, max(0, sw - 1)))
            cy = int(_clamp(cy_f * sh, 0, max(0, sh - 1)))
            cw = int(_clamp(cw_f * sw, 1, sw - cx))
            ch = int(_clamp(ch_f * sh, 1, sh - cy))
        else:
            cx = int(max(0, cx_f))
            cy = int(max(0, cy_f))
            cw = int(max(1, cw_f))
            ch = int(max(1, ch_f))
        parts.append(f"crop={cw}:{ch}:{cx}:{cy}")

    rot = ((float(rotation) % 360) + 360) % 360
    if abs(rot - 90) < 0.01:
        parts.append("transpose=1")
    elif abs(rot - 180) < 0.01:
        parts.append("transpose=1,transpose=1")
    elif abs(rot - 270) < 0.01:
        parts.append("transpose=2")
    elif rot > 0.01:
        rad = rot * 3.141592653589793 / 180.0
        parts.append(f"rotate={rad}:fillcolor=black@1:ow=rotw({rad}):oh=roth({rad})")

    brightness = s["brightness"] / 100.0 + (s["exposure"] / 100.0) * 0.5
    contrast = 1.0 + s["contrast"] / 100.0
    saturation = s["saturation"] / 100.0
    gamma = float(s["gamma"])
    eq_bits = []
    if abs(brightness) > 1e-6:
        eq_bits.append(f"brightness={_clamp(brightness, -1, 1):.4f}")
    if abs(contrast - 1.0) > 1e-6:
        eq_bits.append(f"contrast={_clamp(contrast, 0, 3):.4f}")
    if abs(saturation - 1.0) > 1e-6 and not s["grayscale"]:
        eq_bits.append(f"saturation={_clamp(saturation, 0, 3):.4f}")
    if abs(gamma - 1.0) > 1e-6:
        eq_bits.append(f"gamma={_clamp(gamma, 0.1, 10):.4f}")
    if eq_bits:
        parts.append("eq=" + ":".join(eq_bits))

    if s["grayscale"]:
        parts.append("hue=s=0")
    elif abs(s["hueRotate"]) > 1e-6:
        parts.append(f"hue=h={float(s['hueRotate']):.3f}")

    if s["invert"] > 0:
        # Partial invert approximated by full negate when >= 50, else skip partial.
        if s["invert"] >= 50:
            parts.append("negate")

    if s["sepia"] > 0:
        # Standard sepia channel mixer; strength approximated by always applying when > 0.
        parts.append(
            "colorchannelmixer="
            "rr=0.393:rg=0.769:rb=0.189:"
            "gr=0.349:gg=0.686:gb=0.168:"
            "br=0.272:bg=0.534:bb=0.131"
        )

    if s["blur"] > 0:
        sigma = _clamp(float(s["blur"]), 0, 20)
        parts.append(f"gblur=sigma={sigma:.2f}")

    if s["sharpen"]:
        parts.append("unsharp=5:5:0.8:5:5:0.0")

    if s["vignette"] > 0:
        # vignette angle: smaller = stronger. Map 0–100 → PI/5 .. PI/2-ish weaker.
        amount = _clamp(s["vignette"] / 100.0, 0, 1)
        angle = 3.141592653589793 / 5 + (1 - amount) * (3.141592653589793 / 5)
        parts.append(f"vignette=angle={angle:.4f}")

    tr = s["tintRed"] / 100.0
    tg = s["tintGreen"] / 100.0
    tb = s["tintBlue"] / 100.0
    if abs(tr) > 1e-6 or abs(tg) > 1e-6 or abs(tb) > 1e-6:
        parts.append(
            "colorbalance="
            f"rs={_clamp(tr, -1, 1):.3f}:gs={_clamp(tg, -1, 1):.3f}:bs={_clamp(tb, -1, 1):.3f}"
        )

    return ",".join(parts)


def _encode_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-y",
    ]


def apply_edits(
    src: str | Path,
    dest: str | Path,
    *,
    filters: dict[str, Any] | None = None,
    crop: dict[str, Any] | None = None,
    rotation: float = 0,
    trim: dict[str, Any] | None = None,
) -> Path:
    """Apply filter/crop/rotate/trim and write dest (mp4)."""
    ffmpeg = _require_ffmpeg()
    source = Path(src)
    out = Path(dest)
    if not source.is_file():
        raise FileNotFoundError(f"Video not found: {source}")
    out.parent.mkdir(parents=True, exist_ok=True)

    info = probe_video_info(source)
    vf = build_filtergraph(
        filters,
        crop=crop,
        rotation=rotation,
        source_width=int(info.get("width") or 0),
        source_height=int(info.get("height") or 0),
    )

    cmd = [ffmpeg, *_ffmpeg_quiet_args()]
    start = None
    end = None
    if trim:
        start = float(trim.get("start") or 0)
        end = trim.get("end")
        if end is not None:
            end = float(end)
        if start > 0:
            cmd.extend(["-ss", f"{start:.3f}"])
        if end is not None and end > start:
            cmd.extend(["-to", f"{end:.3f}"])

    cmd.extend(["-i", str(source)])
    if vf:
        cmd.extend(["-vf", vf])
    cmd.extend(_encode_args())
    cmd.append(str(out))

    # If nothing to do, copy bytes (faster).
    if not vf and (start is None or start <= 0) and end is None:
        shutil.copyfile(source, out)
        return out

    proc = _run(cmd)
    if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0:
        return out

    # Retry without audio (some Veo/clips may lack an audio stream).
    cmd_an = [ffmpeg, *_ffmpeg_quiet_args()]
    if start is not None and start > 0:
        cmd_an.extend(["-ss", f"{start:.3f}"])
    if end is not None and (start is None or end > start):
        cmd_an.extend(["-to", f"{end:.3f}"])
    cmd_an.extend(["-i", str(source)])
    if vf:
        cmd_an.extend(["-vf", vf])
    cmd_an.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-an",
            "-movflags",
            "+faststart",
            "-y",
            str(out),
        ]
    )
    proc2 = _run(cmd_an)
    if proc2.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        err = (proc2.stderr or proc.stderr or "").strip() or "ffmpeg edit failed"
        raise RuntimeError(err)
    return out


def trim_segment(
    src: str | Path,
    dest: str | Path,
    start: float,
    end: float,
) -> Path:
    """Cut [start, end) from src into dest (re-encode for reliable concat)."""
    ffmpeg = _require_ffmpeg()
    source = Path(src)
    out = Path(dest)
    if not source.is_file():
        raise FileNotFoundError(f"Video not found: {source}")
    out.parent.mkdir(parents=True, exist_ok=True)

    start_s = max(0.0, float(start))
    end_s = float(end)
    if end_s <= start_s + 0.04:
        raise ValueError("Trim segment too short")
    dur = end_s - start_s

    cmd = [
        ffmpeg,
        *_ffmpeg_quiet_args(),
        "-ss",
        f"{start_s:.3f}",
        "-i",
        str(source),
        "-t",
        f"{dur:.3f}",
        *_encode_args(),
        str(out),
    ]
    proc = _run(cmd)
    if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0:
        return out

    cmd_an = [
        ffmpeg,
        *_ffmpeg_quiet_args(),
        "-ss",
        f"{start_s:.3f}",
        "-i",
        str(source),
        "-t",
        f"{dur:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-an",
        "-movflags",
        "+faststart",
        "-y",
        str(out),
    ]
    proc2 = _run(cmd_an)
    if proc2.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        err = (proc2.stderr or proc.stderr or "").strip() or "ffmpeg trim failed"
        raise RuntimeError(err)
    return out


def assemble_segments(
    src: str | Path,
    dest: str | Path,
    segments: list[dict[str, Any]],
    *,
    filters: dict[str, Any] | None = None,
    crop: dict[str, Any] | None = None,
    rotation: float = 0,
) -> Path:
    """
    Build dest by cutting ordered source ranges then applying filters/crop/rotate.

    segments: list of {start, end} in seconds on the source timeline.
    """
    source = Path(src)
    out = Path(dest)
    if not source.is_file():
        raise FileNotFoundError(f"Video not found: {source}")

    ranges: list[tuple[float, float]] = []
    for raw in segments or []:
        if not isinstance(raw, dict):
            continue
        start = float(raw.get("start") or 0)
        end = float(raw.get("end") or 0)
        if end - start < 0.05:
            continue
        ranges.append((max(0.0, start), end))
    if not ranges:
        raise ValueError("At least one segment is required")

    # Single range: one-pass trim + filters
    if len(ranges) == 1:
        start, end = ranges[0]
        return apply_edits(
            source,
            out,
            filters=filters,
            crop=crop,
            rotation=rotation,
            trim={"start": start, "end": end},
        )

    temps: list[Path] = []
    mid: Path | None = None
    try:
        for i, (start, end) in enumerate(ranges):
            part = temp_mp4_path(f"r98seg_{i}_")
            temps.append(part)
            trim_segment(source, part, start, end)
        mid = temp_mp4_path("r98seg_mid_")
        concat_videos(temps, mid)
        return apply_edits(
            mid,
            out,
            filters=filters,
            crop=crop,
            rotation=rotation,
        )
    finally:
        for p in temps:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        if mid is not None:
            try:
                mid.unlink(missing_ok=True)
            except OSError:
                pass


def split_at(src: str | Path, dest_a: str | Path, dest_b: str | Path, t: float) -> tuple[Path, Path]:
    duration = probe_duration(src)
    if t <= 0 or t >= duration:
        raise ValueError(f"Split time must be between 0 and duration ({duration:.2f}s)")
    a = trim_segment(src, dest_a, 0, t)
    b = trim_segment(src, dest_b, t, duration)
    return a, b


def concat_videos(paths: list[str | Path], dest: str | Path) -> Path:
    """Re-encode concat of multiple videos into dest."""
    if len(paths) < 2:
        raise ValueError("Need at least two videos to splice")
    ffmpeg = _require_ffmpeg()
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    resolved: list[Path] = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise FileNotFoundError(f"Video not found: {path}")
        resolved.append(path)

    # Filter concat is more reliable across mismatched codecs than demuxer copy.
    # For N inputs: [0:v][0:a][1:v][1:a]...concat=n=N:v=1:a=1[v][a]
    cmd = [ffmpeg, *_ffmpeg_quiet_args()]
    for path in resolved:
        cmd.extend(["-i", str(path)])

    n = len(resolved)
    # Scale/pad each to a common size then concat — use first video's size as target.
    info0 = probe_video_info(resolved[0])
    tw = max(2, int(info0.get("width") or 1280))
    th = max(2, int(info0.get("height") or 720))
    # Ensure even dimensions for yuv420p
    tw -= tw % 2
    th -= th % 2

    filter_parts: list[str] = []
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}]"
        )
        filter_parts.append(
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]"
        )
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(f"{concat_in}concat=n={n}:v=1:a=1[v][a]")
    filtergraph = ";".join(filter_parts)

    cmd.extend(
        [
            "-filter_complex",
            filtergraph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            *_encode_args(),
            str(out),
        ]
    )
    proc = _run(cmd, timeout=1200)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        # Retry without audio if some clips lack an audio stream.
        return _concat_video_only(resolved, out, tw, th)
    return out


def _concat_video_only(
    resolved: list[Path], out: Path, tw: int, th: int
) -> Path:
    ffmpeg = _require_ffmpeg()
    n = len(resolved)
    cmd = [ffmpeg, *_ffmpeg_quiet_args()]
    for path in resolved:
        cmd.extend(["-i", str(path)])
    filter_parts: list[str] = []
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}]"
        )
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filter_parts.append(f"{concat_in}concat=n={n}:v=1:a=0[v]")
    filtergraph = ";".join(filter_parts)
    cmd.extend(
        [
            "-filter_complex",
            filtergraph,
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-an",
            "-movflags",
            "+faststart",
            "-y",
            str(out),
        ]
    )
    proc = _run(cmd, timeout=1200)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg concat failed")
    return out


def build_image_slideshow(
    image_paths: list[Path],
    dest: str | Path,
    *,
    seconds_per_image: float = 1.5,
) -> Path:
    """Concatenate stills into an H.264 MP4 slideshow."""
    ffmpeg = _require_ffmpeg()
    paths = [Path(p) for p in image_paths if p and Path(p).is_file()]
    if len(paths) < 2:
        raise ValueError("Slideshow needs at least two images")
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.2, min(8.0, float(seconds_per_image or 1.5)))
    list_file = out.with_suffix(".concat.txt")
    try:
        lines: list[str] = []
        for path in paths:
            escaped = str(path.resolve()).replace("\\", "/").replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
            lines.append(f"duration {duration:.3f}")
        last = str(paths[-1].resolve()).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{last}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            ffmpeg,
            *_ffmpeg_quiet_args(),
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-an",
            "-movflags",
            "+faststart",
            "-y",
            str(out),
        ]
        proc = _run(cmd, timeout=1200)
        if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError(proc.stderr.strip() or "ffmpeg slideshow failed")
        return out
    finally:
        try:
            list_file.unlink(missing_ok=True)
        except OSError:
            pass


def temp_mp4_path(prefix: str = "r98vid_") -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".mp4")
    os.close(fd)
    return Path(name)
