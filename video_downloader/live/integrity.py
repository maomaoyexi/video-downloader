"""File-level evidence, not a claim that the platform supplied every segment."""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

from .process import hidden_options


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


class IntegrityChecker:
    def __init__(self, ffprobe, ffmpeg, *, timeout=120):
        self.ffprobe, self.ffmpeg, self.timeout = str(ffprobe), str(ffmpeg), timeout

    def inspect(self, path, expected="av"):
        path = Path(path)
        result = {"path": str(path), "size": 0, "errors": [],
                  "container": "", "duration": 0, "streams": [], "timestamps": {}, "warnings": [],
                  "decode_scope": "first_and_last_10_seconds", "valid": False}
        try:
            result["size"] = path.stat().st_size
        except OSError:
            result["errors"].append("missing_file")
            return result
        if result["size"] == 0:
            result["errors"].append("empty_file")
            return result
        try:
            completed = subprocess.run(
                [self.ffprobe, "-v", "error", "-show_error", "-show_format", "-show_streams", "-show_data_hash", "sha256",
                 "-of", "json", str(path)], capture_output=True, timeout=self.timeout, **hidden_options())
            metadata = json.loads(completed.stdout or b"{}")
            if completed.returncode or completed.stderr or metadata.get("error"):
                result["errors"].append("ffprobe_error")
            streams = metadata.get("streams", [])
            result["streams"] = [{**{key: stream.get(key) for key in
                                  ("index", "codec_type", "codec_name", "width", "height", "sample_rate",
                                   "channels", "start_time", "duration", "time_base", "avg_frame_rate", "extradata_hash")},
                                  "attached_pic": bool(stream.get("disposition", {}).get("attached_pic"))} for stream in streams]
            kinds = {stream.get("codec_type") for stream in streams if not stream.get("disposition", {}).get("attached_pic")}
            if ("a" in expected and "audio" not in kinds) or ("v" in expected and "video" not in kinds):
                result["errors"].append("missing_track")
            result["container"] = metadata.get("format", {}).get("format_name", "")
            result["duration"] = number(metadata.get("format", {}).get("duration"))
            # Scan all packet timestamps without loading hours of JSON into RAM.
            with tempfile.TemporaryFile() as packets:
                scan = subprocess.run(
                    [self.ffprobe, "-v", "error", "-show_packets", "-show_entries",
                     "packet=stream_index,pts_time,dts_time,duration_time", "-of", "compact=p=0:nk=0", str(path)],
                    stdout=packets, stderr=subprocess.PIPE, timeout=self.timeout, **hidden_options())
                if scan.returncode or scan.stderr:
                    result["errors"].append("packet_scan_error")
                packets.seek(0)
                for line in packets:
                    values = dict(item.split("=", 1) for item in line.decode("utf-8", "replace").strip().split("|") if "=" in item)
                    if "stream_index" not in values:
                        continue
                    stamp = number(values.get("dts_time"), None)
                    pts = number(values.get("pts_time"), None)
                    if stamp is None:
                        stamp = pts
                    if stamp is None:
                        continue
                    key = values["stream_index"]
                    track = result["timestamps"].setdefault(key, {"first": stamp, "last": stamp, "packets": 0,
                                                                "max_gap": 0, "backwards": 0,
                                                                "max_pts_gap": 0, "max_presentation_delay": 0})
                    if pts is not None:
                        if 'last_pts' in track:
                            track['max_pts_gap'] = max(track['max_pts_gap'], abs(pts - track['last_pts']))
                        track['last_pts'] = pts
                        track['max_presentation_delay'] = max(track['max_presentation_delay'], abs(pts - stamp))
                    if track["packets"]:
                        delta = stamp - track["last"]
                        track["max_gap"] = max(track["max_gap"], delta)
                        track["backwards"] += int(delta < -0.5)
                    track["last"], track["packets"] = stamp, track["packets"] + 1
            if not result["timestamps"]:
                result["errors"].append("no_packets")
            if result["duration"] <= 0 and result["timestamps"]:
                result["duration"] = max(t["last"] - t["first"] for t in result["timestamps"].values())
            if result["duration"] <= 0:
                result["errors"].append("invalid_duration")
            limits = {}
            for stream in streams:
                rate = str(stream.get("avg_frame_rate", "0/1")).split("/")
                fps = number(rate[0]) / (number(rate[1], 1) or 1) if len(rate) == 2 else number(rate[0])
                limits[str(stream.get("index"))] = max(1, 5 / fps) if fps else (1 if stream.get("codec_type") == "audio" else 5)
            if any(t['backwards'] for t in result['timestamps'].values()):
                result["errors"].append("timestamp_discontinuity")
            elif any(t['max_gap'] > limits.get(key, 1) for key, t in result['timestamps'].items()):
                # A forward gap leaves a playable recording with missing media.
                # Preserve it as usable and report gaps rather than corruption.
                result['warnings'].append('timestamp_discontinuity')
            # Decode timestamps can remain monotonic while a corrupt video PTS
            # stretches an 80-second capture to an hour. Small B-frame reorder
            # is normal; large presentation jumps/delays cannot pass integrity.
            if any(t['max_presentation_delay'] > max(5, limits.get(key, 5))
                   or (t['max_pts_gap'] > max(5, limits.get(key, 5)) and t['max_gap'] <= limits.get(key, 1))
                   for key, t in result['timestamps'].items()):
                result['errors'].append('presentation_timestamp_discontinuity')
            for start in sorted({0, max(0, result["duration"] - 10)}):
                decode = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-ss", str(start), "-i", str(path),
                     "-t", "10", "-map", "0:v?", "-map", "0:a?", "-f", "null", "-"],
                    capture_output=True, timeout=self.timeout, **hidden_options())
                if decode.returncode:
                    result["errors"].append("decode_sample_error")
                    break
                if decode.stderr:
                    result["warnings"].append("decode_boundary_diagnostics")
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            result["errors"].append(type(exc).__name__)
        result["errors"] = list(dict.fromkeys(result["errors"]))
        result["valid"] = not result["errors"]
        return result

    def report(self, paths, *, reason, exit_codes, mode, expected="av", retries=0, forced=False,
               warnings=(), webhook_complete=True):
        files = [self.inspect(path, expected(path) if callable(expected) else "" if expected == "separate" else expected) for path in paths]
        usable = any(file["valid"] for file in files)
        issues = list(warnings)
        missing_pair = expected == "separate" and not {"audio", "video"}.issubset(
            {s.get("codec_type") for file in files for s in file.get("streams", []) if not s.get("attached_pic")})
        if missing_pair:
            issues.append("missing_track_pair")
        issues.extend(dict.fromkeys(w for file in files for w in file.get('warnings', [])))
        if retries:
            issues.append("recording_restarted_possible_gap")
        if forced:
            issues.append("forced_termination")
        if not webhook_complete:
            issues.append("webhook_close_not_confirmed")
        if reason == 'user' and not files:
            conclusion = 'cancelled_before_recording'
        elif reason in {"crash", "error", "disk_full", "watchdog"}:
            conclusion = "failed"
        elif not usable or missing_pair:
            conclusion = "failed"
        elif issues or not all(file["valid"] for file in files):
            conclusion = "gaps"
        elif mode == "catch_up":
            conclusion = "from_earliest_available"
        else:
            conclusion = "complete"
        return {"schema_version": 1, "conclusion": conclusion, "stop_reason": reason,
                "scope": "recording_interval_only", "segment_completeness_verified": False,
                "files": files, "exit_codes": exit_codes, "warnings": issues,
                "decode_scope": "first_and_last_10_seconds"}

    def concatenate(self, session, report):
        files = report["files"]
        if len(files) < 2 or not all(f["valid"] for f in files):
            return
        def signature(file):
            return [{key: s.get(key) for key in ("codec_type", "codec_name", "width", "height", "sample_rate", "channels")}
                    for s in file["streams"]]
        if any(signature(f) != signature(files[0]) for f in files[1:]):
            report["warnings"].append("concat_incompatible_tracks_parts_retained")
            return
        listing = session.root / "concat.txt"
        joined = session.root / "joined.mkv"
        try:
            listing.write_text("".join("file '" + Path(f["path"]).as_posix().replace("'", "'\\''") + "'\n" for f in files), encoding="utf-8")
            result = subprocess.run([self.ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-y", "-f", "concat",
                                     "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)],
                                    capture_output=True, timeout=self.timeout, **hidden_options())
            if result.returncode == 0:
                verified = self.inspect(joined)
                if verified["valid"]:
                    report["joined"] = verified
                    return
            report["warnings"].append("concat_failed_parts_retained")
            joined.unlink(missing_ok=True)
        except (OSError, subprocess.TimeoutExpired):
            report["warnings"].append("concat_failed_parts_retained")
        finally:
            listing.unlink(missing_ok=True)
