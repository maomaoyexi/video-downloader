"""A worker losing ownership between renewal and saving cannot overwrite a successor."""
from .test_lease_regressions import setup_archive


def test_archive_save_does_not_overwrite_a_worker_that_took_over_after_renewal(tmp_path, monkeypatch):
    app, job, now, cancel = setup_archive(tmp_path)
    repository = app.repository
    save_job = repository.save_job
    successors = []

    def save_after_owner_switch(state, *args, **kwargs):
        if state['id'] == job['id'] and state['status'] == 'running' and not successors:
            now[0] += 121
            token, _ = repository.acquire('job:' + job['id'])
            assert token is not None
            successors.append(token)
            successor = repository.job(job['id'])
            successor['status'] = 'running'
            successor['worker_marker'] = 'successor owns this state'
            save_job(successor)
        return save_job(state, *args, **kwargs)

    monkeypatch.setattr(repository, 'save_job', save_after_owner_switch)
    try:
        app.run(job['id'], cancel=cancel)
        saved = repository.job(job['id'])
        assert successors, 'The reproduction must actually transfer ownership'
        assert saved.get('worker_marker') == 'successor owns this state'
        assert saved['status'] == 'running'
    finally:
        for token in successors:
            repository.release(token)


def test_terminal_save_respects_a_successor_even_before_its_first_save(tmp_path):
    app, job, now, _ = setup_archive(tmp_path)
    repository = app.repository
    state = repository.job(job['id'])
    old_token, _ = repository.acquire('job:' + job['id'])
    now[0] += 121
    successor, _ = repository.acquire('job:' + job['id'])
    assert successor is not None
    try:
        state['status'] = 'paused'
        assert repository.save_terminal_job(state, old_token) is False
        saved = repository.job(job['id'])
        assert saved['status'] == 'queued'
        assert saved['version'] == state['version']
        assert repository.has_lease('job:' + job['id'])
    finally:
        repository.release(successor)


def test_terminal_save_respects_a_newer_persisted_version_after_owner_release(tmp_path):
    app, job, _, _ = setup_archive(tmp_path)
    repository = app.repository
    stale = repository.job(job['id'])
    token, _ = repository.acquire('job:' + job['id'])
    newer = repository.job(job['id'])
    newer['status'] = 'completed'
    newer['worker_marker'] = 'newer state must survive'
    repository.save_job(newer)
    repository.release(token)
    stale['status'] = 'paused'
    assert repository.save_terminal_job(stale, token) is False
    saved = repository.job(job['id'])
    assert saved['version'] == newer['version']
    assert saved['status'] == 'completed'
    assert saved['worker_marker'] == 'newer state must survive'
