"""RPlay reuses yt-dlp lifecycle, revalidating the room on each reconnect."""

from .ytdlp import YtDlpEngine
from ..probe import YtDlpProbe, LiveStatus, ProbeError
from ..urls import classify_target


class RplayEngine(YtDlpEngine):
    def __init__(self, command, url, *, probe=None):
        super().__init__(command)
        self.target = classify_target(url, 'Rplay')
        self._probe = probe or YtDlpProbe(command[0], command_context=lambda target: self.original)
        self._started_at = None
        self._media_identity = None

    def command(self, directory):
        status = self._probe.probe(self.target)
        if status.status in {LiveStatus.ERROR, LiveStatus.UNKNOWN}:
            raise ProbeError('rplay_source_probe_unavailable', retryable=status.retryable)
        if status.status is not LiveStatus.LIVE:
            raise PermissionError('rplay_source_not_available')
        if self._started_at is not None and status.started_at != self._started_at:
            raise PermissionError('rplay_source_instance_changed')
        self._started_at = status.started_at
        return super().command(directory)

    def observe_metadata(self, metadata):
        identity = (metadata.get('id'), metadata.get('timestamp'))
        if not identity[0] or identity[1] is None:
            raise PermissionError('rplay_media_identity_unavailable')
        if self._media_identity is not None and identity != self._media_identity:
            raise PermissionError('rplay_media_instance_changed')
        self._media_identity = identity

    def source_ended(self):
        try:
            status = self._probe.probe(self.target)
        except ProbeError as exc:
            if exc.status is LiveStatus.PRIVATE or not exc.retryable:
                raise PermissionError('rplay_source_permission_revoked') from None
            return False
        if status.status is LiveStatus.PRIVATE:
            raise PermissionError('rplay_source_permission_revoked')
        if status.status in {LiveStatus.OFFLINE, LiveStatus.ENDED}:
            return True
        if status.status is LiveStatus.LIVE:
            return self._started_at is not None and status.started_at != self._started_at
        return False
