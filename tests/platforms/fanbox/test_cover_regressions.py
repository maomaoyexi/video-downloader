"""Exercise image-type and public-cover regressions through archive boundaries."""
from pathlib import Path
import threading

import pytest

from video_downloader.platforms.fanbox.archive import ArchiveApplication
from video_downloader.platforms.fanbox.controller import FanboxController
from video_downloader.platforms.fanbox.downloader import Downloader, digest_file, resource_key
from video_downloader.platforms.fanbox.errors import FanboxError
from video_downloader.platforms.fanbox.models import Asset, Post
from video_downloader.platforms.fanbox.naming import asset_path, confined
from video_downloader.platforms.fanbox.options import normalize_options
from video_downloader.platforms.fanbox.parsers import parse_post
from video_downloader.platforms.fanbox.presentation import asset_rows
from video_downloader.platforms.fanbox.repository import Repository
from video_downloader.platforms.fanbox.scheduling import AccountGate
from .test_archive_io import Body, DATE
from .test_content import image, post
from .test_scan import FakeTransport


JPEG = b'\xff\xd8\xff' + b'synthetic image payload'
PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic image payload'
NETWORK = {'api_interval_seconds': 0, 'file_start_interval_seconds': 0}


def download_image(tmp_path, value, *, quality='thumbnail', data=JPEG):
    options = normalize_options({'content': {'image_quality': quality}, 'network': NETWORK})
    model = parse_post(value, options)
    repository = Repository(tmp_path / '.fanbox/library.sqlite')
    transport = Body(data)
    downloader = Downloader(tmp_path, repository, AccountGate(repository, threading.Event(), 0), transport)
    result = downloader.download(model, model.assets[0], options, DATE)
    assert result['status'] == 'completed'
    assert (tmp_path / result['path']).read_bytes() == data
    return model.assets[0], result


@pytest.mark.parametrize('original_extension', ['png', 'gif'])
def test_selected_thumbnail_uses_downloaded_image_type(tmp_path, original_extension):
    source = image()
    source['extension'] = original_extension
    source['originalUrl'] = source['originalUrl'].rsplit('.', 1)[0] + '.' + original_extension
    asset, result = download_image(tmp_path, post('image', {'images': [source]}))
    assert asset.extension == 'jpg'
    assert asset.variant == 'thumbnail'
    assert Path(result['path']).suffix == '.jpg'
    assert source['extension'] == original_extension


def test_entry_thumbnail_uses_its_url_type_instead_of_original_type(tmp_path):
    value = post('entry', {'html': '<a href="https://downloads.fanbox.cc/images/original.png">'
                         '<img src="https://downloads.fanbox.cc/images/thumb.jpg"></a>'})
    asset, result = download_image(tmp_path, value)
    assert asset.extension == 'jpg'
    assert Path(result['path']).suffix == '.jpg'


def test_original_image_keeps_its_type_and_strict_signature_check(tmp_path):
    asset, result = download_image(tmp_path, post('image', {'images': [image()]}), quality='original', data=PNG)
    assert asset.extension == 'png'
    assert asset.variant == 'original'
    assert Path(result['path']).suffix == '.png'


def test_normalizing_thumbnail_extension_keeps_payload_validation_strict(tmp_path):
    with pytest.raises(FanboxError) as error:
        download_image(tmp_path, post('image', {'images': [image()]}), data=PNG)
    assert error.value.code == 'invalid_payload'


def test_restricted_snapshot_projects_only_public_cover_as_selectable():
    value = post()
    value['body'] = None
    value['coverImageUrl'] = 'https://pixiv.pximg.net/fanbox/public/cover.jpg'
    model = parse_post(value)
    model.assets.append(Asset('private', 'image', 'private', 'png', 'https://downloads.fanbox.cc/private.png'))
    rows = asset_rows({'task_date': DATE}, model, normalize_options())
    assert rows[0]['selected'] is True
    assert rows[1]['selected'] is False
    assert rows[1]['reason'] == 'restricted_body'


@pytest.mark.parametrize('existing_jpeg', [False, True])
def test_old_thumbnail_snapshot_and_failed_allocation_resume_with_correct_type(tmp_path, existing_jpeg):
    value = post('image', {'images': [image()]})

    class JsonTransport(FakeTransport):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    binary = Body(JPEG)
    app = ArchiveApplication(tmp_path, transport_factory=lambda *a, **kw: JsonTransport([[value]]),
                             binary_factory=lambda *a, **kw: binary)
    job = app.create('https://sample.fanbox.cc', {'network': NETWORK, 'content': {'image_quality': 'thumbnail'}})
    assert app.run(job['id'], preview=True)['status'] == 'preview_ready'
    state = app.repository.job(job['id'])
    snapshot = state['scan']['posts'][0]
    snapshot['assets'][0]['extension'] = 'png'
    legacy_asset = Asset(**snapshot['assets'][0])
    model = Post.from_dict(snapshot)
    key = resource_key(model, legacy_asset)
    legacy_path = asset_path(model, legacy_asset, state['options'], state['task_date'])
    assert legacy_path.endswith('.png')
    app.repository.allocate(key, legacy_path)
    old_file = confined(tmp_path, legacy_path, create=True)
    old_file.write_bytes(b'user file kept at original path')
    corrected_path = old_file.with_suffix('.jpg')
    if existing_jpeg:
        corrected_path.write_bytes(b'another user file')
    state['status'] = 'failed'
    state['files'] = {'1': {'img1:thumbnail': {'status': 'failed', 'error': {'code': 'invalid_payload'}}}}
    app.repository.save_job(state)

    result = app.run(job['id'])
    assert result['status'] == 'completed'
    assert result['counts']['completed'] == 1
    saved = app.repository.job(job['id'])
    record = saved['files']['1']['img1:thumbnail']
    assert Path(record['path']).suffix == '.jpg'
    assert app.repository.asset(key)['path'] == record['path']
    assert (tmp_path / record['path']).read_bytes() == JPEG
    assert old_file.read_bytes() == b'user file kept at original path'
    if existing_jpeg:
        assert corrected_path.read_bytes() == b'another user file'
        assert record['path'].endswith(' (1).jpg')


def test_correcting_old_thumbnail_metadata_preserves_completed_files(tmp_path):
    options = normalize_options({'network': NETWORK, 'content': {'image_quality': 'thumbnail'}})
    snapshot = parse_post(post('image', {'images': [image()]}), options).to_dict()
    snapshot['assets'][0]['extension'] = 'png'
    legacy_asset = Asset(**snapshot['assets'][0])
    model = Post.from_dict(snapshot)
    repository = Repository(tmp_path / '.fanbox/library.sqlite')
    key = resource_key(model, legacy_asset)
    legacy_path = asset_path(model, legacy_asset, options, DATE)
    repository.allocate(key, legacy_path)
    target = confined(tmp_path, legacy_path, create=True)
    target.write_bytes(PNG)
    repository.save_asset(key, {'status': 'completed', 'size': len(PNG), 'sha256': digest_file(target),
                                'path': legacy_path, 'variant': 'thumbnail'})
    binary = Body(JPEG)
    downloader = Downloader(tmp_path, repository, AccountGate(repository, threading.Event(), 0), binary)
    result = downloader.download(model, model.assets[0], options, DATE)
    assert result['status'] == 'reused'
    assert result['path'] == legacy_path
    assert target.read_bytes() == PNG
    assert not binary.requests


@pytest.fixture
def restricted_preview(tmp_path):
    value = post()
    value['body'] = None
    value['coverImageUrl'] = 'https://pixiv.pximg.net/fanbox/public/cover.jpg'

    class JsonTransport(FakeTransport):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    binary = Body(JPEG)
    app = ArchiveApplication(tmp_path / 'files',
        transport_factory=lambda *args, **kwargs: JsonTransport([[value]]),
        binary_factory=lambda *args, **kwargs: binary)
    launches = []
    controller = FanboxController(app, tool_dir=tmp_path, config_getter=lambda: {},
        start=lambda *args: launches.append(args) or {'ok': True, 'task': {'id': 'cover-task'}},
        cancel=lambda *args: None)
    try:
        job_id = controller.create({'url': 'https://sample.fanbox.cc', 'request_id': 'restricted-preview',
                                    'preview': True, 'options': {'network': NETWORK}})['job']['id']
        assert app.run(job_id, preview=True)['status'] == 'preview_ready'
        controller.finished(job_id)
        state = app.repository.job(job_id)
        assert state['scan']['posts'][0]['access'] == 'restricted'
        assert not binary.requests
        yield app, controller, state, binary
    finally:
        controller.stop()


@pytest.mark.parametrize('selection', [{}, {'post_ids': ['1']}, {'asset_ids': ['1:cover:original']}])
def test_preview_download_saves_restricted_post_public_cover(restricted_preview, selection):
    app, controller, state, binary = restricted_preview
    controller.action({'id': state['id'], 'version': state['version'], 'action': 'download', 'selection': selection})
    result = app.run(state['id'])
    assert result['status'] == 'partial'
    assert result['counts']['restricted'] == 1
    assert result['counts']['completed'] == 1
    assert result['counts']['failed'] == 0
    assert len(binary.requests) == 1
    saved = app.repository.job(state['id'])
    assert list(saved['files']['1']) == ['cover:original']
    assert (app.root / saved['files']['1']['cover:original']['path']).read_bytes() == JPEG
    assert saved['scan']['posts'][0]['blocks'] == []


def test_public_cover_can_be_excluded_without_accessing_restricted_body(restricted_preview):
    app, controller, state, binary = restricted_preview
    controller.action({'id': state['id'], 'version': state['version'], 'action': 'download',
                       'selection': {'exclude_post_ids': ['1']}})
    result = app.run(state['id'])
    assert result['counts']['completed'] == 0
    assert not binary.requests


def test_explicit_accessible_only_selection_still_skips_restricted_posts(restricted_preview):
    app, controller, state, binary = restricted_preview
    controller.action({'id': state['id'], 'version': state['version'], 'action': 'download',
                       'selection': {'accessible_only': True}})
    result = app.run(state['id'])
    assert result['counts']['completed'] == 0
    assert not binary.requests


def test_disabled_cover_is_not_downloaded_from_restricted_preview(restricted_preview):
    app, controller, state, binary = restricted_preview
    state['options']['content']['cover'] = False
    state['scan']['posts'][0]['assets'][0]['selected'] = False
    state['scan']['posts'][0]['assets'][0]['skip_reason'] = 'cover_disabled'
    app.repository.save_job(state)
    saved = app.repository.job(state['id'])
    controller.action({'id': state['id'], 'version': saved['version'], 'action': 'download'})
    result = app.run(state['id'])
    assert result['counts']['completed'] == 0
    assert not binary.requests
