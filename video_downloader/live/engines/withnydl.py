"""Managed Withny watch configuration; original credentials/config remain untouched."""
from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import replace
from pathlib import Path

from ..danmaku.dependencies import library
from ..danmaku.timeline import epoch
from ..session import media_files
from . import EngineFeatures


def managed_binary(dependency_dir):
    """Use only the managed, checksum-matching native chat adaptation."""
    directory = Path(dependency_dir) / 'Withny'
    executable, manifest = directory / 'withny-dl.exe', directory / 'manifest.json'
    try:
        if manifest.stat().st_size > 16384:
            return None
        info = json.loads(manifest.read_text(encoding='utf-8'))
        if isinstance(info, dict) and info.get('version') == '2.0.0-local-chat-1':
            with executable.open('rb') as source:
                digest = hashlib.sha256()
                for chunk in iter(lambda:source.read(1024 * 1024), b''):
                    digest.update(chunk)
                if digest.hexdigest() == info['sha256']:
                    return executable
    except (OSError, ValueError, KeyError):
        pass
    return None


class WithnyEngine:
    name = "withny-dl"
    features = EngineFeatures(managed_outputs=True, per_file_tracks=True, annotate_report=True,
                              original_working_directory=True, concatenate=False, clock_source=True, native_waiting=True)

    def __init__(self, command, session, config_path, comments, *, managed=True):
        self.original, self.session = list(command), session
        if not managed:
            # 旧组件没有等待状态事件，由它自身负责监控和重试。
            self.features = replace(self.features, native_waiting=False, media_watchdog=False)
        self.config_path = Path(config_path)
        self.cwd = self.config_path.parent
        self.comments = comments
        self.private = session.root / "withny.private.yaml"
        self.private_cache = session.root / 'withny-cache.private.json'
        self.audio_channels = set()
        self.poll_states, self.active_streams = {}, set()

    def command(self, directory):
        if self.config_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("withny_config_too_large")
        yaml = library("ruamel.yaml").YAML(typ="safe", pure=True)
        data = yaml.load(self.config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("channels"), dict) or not data["channels"]:
            raise ValueError("withny_channels_required")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", str(key)) for key in data["channels"]):
            raise ValueError("invalid_withny_channel")
        defaults = data.get("defaultParams") or {}
        if not isinstance(defaults, dict):
            raise ValueError("invalid_withny_defaults")
        defaults = dict(defaults)
        if 'quality' not in defaults and 'qualityConstraint' in defaults:
            defaults['quality'] = defaults['qualityConstraint']
        defaults.pop('qualityConstraint', None)
        common = {"writeChat":self.comments, "writeMetaDataJson":True, "concat":False,
                  "keepIntermediates":True, "deleteCorrupted":False, "scanDirectory":str(directory),
                  "outFormat":str(directory / "{{ .ChannelID }}" / "{{ .MetaData.Stream.UUID }}.{{ .Ext }}")}
        data["defaultParams"] = dict(defaults, **common)
        data['cachedCredentialsFile'] = str(self.private_cache)
        self.poll_states = dict.fromkeys(data['channels'])
        for channel, params in data["channels"].items():
            if params is not None and not isinstance(params, dict):
                raise ValueError("invalid_withny_channel_params")
            params = params or {}
            params = dict(params)
            if 'quality' not in params and 'qualityConstraint' in params:
                params['quality'] = params['qualityConstraint']
            params.pop('qualityConstraint', None)
            quality = params.get('quality', defaults.get('quality', {})) or {}
            if not isinstance(quality, dict):
                raise ValueError('invalid_withny_quality')
            if quality.get("audioOnly"):
                self.audio_channels.add(str(channel))
            data["channels"][channel] = dict(params, **common)
        with self.private.open("w", encoding="utf-8", newline="\n") as output:
            yaml.dump(data, output)
        os.chmod(self.private, 0o600)
        command = list(self.original)
        index = command.index("--config")
        command[index + 1] = str(self.private)
        return command

    def line(self, line):
        if not line.startswith('LIVE_NATIVE_STATE:'):
            return
        try:
            data = json.loads(line.split(':', 1)[1])
            state, channel = data['kind'], data['channel']
            if state == 'started':
                self.active_streams.add(data['stream'])
            elif state == 'finished':
                self.active_streams.discard(data['stream'])
            elif channel in self.poll_states and state in {'idle', 'error', 'online'}:
                self.poll_states[channel] = state
        except (ValueError, KeyError, TypeError):
            return

    @property
    def waiting(self):
        return bool(self.poll_states) and not self.active_streams and all(
            state == 'idle' for state in self.poll_states.values())

    def output_files(self, root):
        preferred = {}
        for path in media_files(root):
            audio = path.suffix.lower() in {".m4a", ".mp3", ".aac", ".wav"}
            key = (str(path.with_suffix("")), audio)
            rank = {".mkv":4, ".mp4":3, ".m4a":3, ".ts":1}.get(path.suffix.lower(), 0)
            if key not in preferred or rank > preferred[key][0]:
                preferred[key] = (rank, path)
        return sorted(pair[1] for pair in preferred.values())

    def expected_tracks(self, path):
        path = Path(path)
        return "a" if path.suffix.lower() in {".m4a", ".mp3", ".aac", ".wav"} or any(
            part in self.audio_channels for part in path.parts) else "av"

    def annotate(self, report):
        for file in report["files"]:
            path = Path(file["path"]).with_suffix(".info.json")
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                info = json.loads(path.read_text(encoding="utf-8"))
                stream = info.get("Stream") or info.get("stream") or {}
                stamp = epoch(stream.get("StartedAt") or stream.get("startedAt"))
                if stamp is not None:
                    file["programme_started_at"] = stamp
                # StartedAt is programme start, not the start of a recording
                # that joined mid-stream. Metadata is written immediately
                # before media recording by the native engine.
                file["anchor_utc"] = path.stat().st_mtime
                file["anchor_source"] = "withny_metadata_write_estimate"
            except (OSError, ValueError, TypeError):
                pass

    def stop_recording(self):
        return

    def clock_metadata(self, directory):
        from ..danmaku.transport import Transport
        yaml = library('ruamel.yaml').YAML(typ='safe', pure=True)
        config = yaml.load(self.private.read_text(encoding='utf-8'))
        info_path = next(Path(directory).rglob('*.info.json'))
        info = json.loads(info_path.read_text(encoding='utf-8'))
        stream_id = (info.get('Stream') or info.get('stream'))['uuid']
        transport = Transport(['withny', '--proxy', ''])
        try:
            # The native cache is encrypted, even with a .json filename. Keep
            # it opaque and use the documented NextAuth session API instead.
            credentials = Path(config['credentialsFile'])
            if not credentials.is_absolute():
                credentials = self.cwd / credentials
            if credentials.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('withny_credentials_too_large')
            saved = yaml.load(credentials.read_text(encoding='utf-8-sig'))
            transport.client.cookies.set('__Secure-next-auth.session-token', saved['sessionToken'],
                                         domain='www.withny.fun', path='/')
            token = transport.json('https://www.withny.fun/api/auth/session')['accessToken']
            playback = transport.json(f'https://www.withny.fun/api/streams/{stream_id}/playback-url',
                                      headers={'Authorization':'Bearer ' + token})
            url = playback if isinstance(playback, str) else playback.get('url') or playback.get('playbackUrl')
            return {'url':url, 'protocol':'m3u8',
                    'http_headers':{'Referer':'https://www.withny.fun/', 'Origin':'https://www.withny.fun'},
                    'height':(config.get('defaultParams', {}).get('quality') or {}).get('maxHeight')}
        finally:
            transport.close()

    def close(self):
        self.private.unlink(missing_ok=True)
        self.private_cache.unlink(missing_ok=True)
