import json
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles

from karpy_platform.core.media import routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(routes.settings, "MEDIA_DIR", public)
    monkeypatch.setattr(routes.settings, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(routes.settings, "THEME_PUBLIC_DIR", tmp_path / "themes")
    user = SimpleNamespace(id="admin-a")
    monkeypatch.setattr(routes, "ensure_admin_user", AsyncMock(return_value=user))
    uploaded = []

    async def upload(db, file, **kwargs):
        uploaded.append((await file.read(), file.filename, file.content_type, kwargs))
        return {"id": "saved"}

    monkeypatch.setattr(routes.rv_media, "upload_file", AsyncMock(side_effect=upload))
    monkeypatch.setattr(routes.rv_media, "file_payload", lambda item: item)
    app = FastAPI()
    app.include_router(routes.router)
    app.mount("/public", StaticFiles(directory=public))
    app.dependency_overrides[routes.get_db] = lambda: None
    with TestClient(app) as http:
        yield SimpleNamespace(http=http, uploaded=uploaded, user=user, tmp=tmp_path, public=public)


def send(client, session=None, index="0", count="2", content=b"first", headers=None, **data):
    mime = data.pop("mime", "text/plain")
    form = {"dzuuid": session or str(uuid4()), "filename": "report.txt",
            "dzchunkindex": index, "dztotalchunkcount": count, **data}
    return client.http.post("/media/files/chunk", data=form,
                            files={"file": ("blob", content, mime)}, headers=headers)


def session_dir(client, session):
    return client.tmp / "storage" / "core-media-chunks" / sha256(client.user.id.encode()).hexdigest() / session


def test_ordered_complete_private_and_idempotent(client):
    session = str(uuid4())
    assert send(client, session, index="1", content=b"second").json() == {"complete": False, "progress": 50}
    assert not client.uploaded
    assert send(client, session, index="1", content=b"second").status_code == 200
    assert send(client, session, index="1", content=b"different").status_code == 409
    assert not list(client.public.iterdir())
    assert client.http.get(f"/public/.chunks/{session}/00000001.part").status_code == 404
    response = send(client, session)
    assert response.json()["complete"] is True
    assert client.uploaded[0][:3] == (b"firstsecond", "report.txt", "text/plain")
    assert send(client, session).json() == response.json()
    assert send(client, session, index="1", content=b"second").json() == response.json()
    assert send(client, session, index="1", content=b"changed").status_code == 409
    assert len(client.uploaded) == 1
    assert {p.name for p in session_dir(client, session).iterdir()} == {"session.json"}


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "C:\\escape", "a\\b", "a/b", "..", "a\x00b", "a\nb", "a\x7fb", " file.txt"])
def test_bad_filename(client, name):
    assert send(client, filename=name).status_code == 400
    assert not (client.tmp / "storage").exists()


@pytest.mark.parametrize("session", ["../escape", "/tmp/escape", "C:\\escape", "x", "0" * 32])
def test_bad_session(client, session):
    assert send(client, session).status_code == 400


@pytest.mark.parametrize("index,count", [("-1", "2"), ("2", "2"), ("0", "0"), ("0", "1025"),
                                         ("0.0", "2"), ("0", "2.0"), ("+0", "2"), (" 0", "2"), ("0", "999999999999")])
def test_bad_numbers(client, index, count):
    assert send(client, index=index, count=count).status_code == 400


@pytest.mark.parametrize("change", [{"filename": "other.txt"}, {"mime": "image/png"},
                                   {"count": "3"}, {"folderId": "other"}, {"visibility": "private"}])
def test_metadata_mismatch(client, change):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    assert send(client, session, index="1", **change).status_code == 409
    assert not client.uploaded


def test_user_isolation_and_metadata_binding(client):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    first_dir = session_dir(client, session)
    client.user.id = "admin-b"
    assert send(client, session, index="1").json()["complete"] is False
    assert not client.uploaded
    manifest = session_dir(client, session) / "session.json"
    manifest.write_bytes((first_dir / "session.json").read_bytes())
    assert send(client, session).status_code == 409


def test_limits(client, monkeypatch):
    monkeypatch.setattr(routes, "CHUNK_MAX_BYTES", 5)
    monkeypatch.setattr(routes, "CHUNK_TOTAL_BYTES", 7)
    assert send(client, content=b"123456").status_code == 413
    session = str(uuid4())
    assert send(client, session, content=b"12345").status_code == 200
    assert send(client, session, index="1", content=b"678").status_code == 413
    monkeypatch.setattr(routes, "CHUNK_MAX_SESSIONS", 1)
    assert send(client).status_code == 429
    assert not client.uploaded


def test_exact_set_and_preserve_unexpected_files(client):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    unexpected = session_dir(client, session) / "unrelated.txt"
    unexpected.write_bytes(b"keep")
    assert send(client, session, index="1").status_code == 409
    assert unexpected.read_bytes() == b"keep"
    assert not client.uploaded


def test_final_validation_and_safe_cleanup(client, monkeypatch):
    monkeypatch.setattr(routes.rv_media, "upload_file", AsyncMock(side_effect=routes.MediaValidationError("blocked")))
    session = str(uuid4())
    assert send(client, session, count="1").status_code == 400
    assert not (session_dir(client, session) / "assembled.upload").exists()
    assert not (client.tmp / "storage" / "core-media-chunks" / ".lock").exists()
    assert (session_dir(client, session) / "00000000.part").read_bytes() == b"first"


@pytest.mark.parametrize("headers", [{"origin": "https://evil.example"}, {"origin": "null"},
                                     {"referer": "https://evil.example/path"}, {"sec-fetch-site": "cross-site"}])
def test_cross_origin(client, headers):
    assert send(client, headers=headers).status_code == 403
    assert not (client.tmp / "storage").exists()


def test_same_origin_and_public_storage_misconfiguration(client, monkeypatch):
    assert send(client, headers={"origin": "http://testserver"}).status_code == 200
    monkeypatch.setattr(routes.settings, "STORAGE_DIR", client.public / "storage")
    assert send(client).status_code == 503
    assert not list(client.public.iterdir())


def test_lock_contention(client):
    root = routes._chunk_root()
    (root / ".lock").mkdir()
    assert send(client).status_code == 409
    assert (root / ".lock").is_dir()


def test_missing_recorded_part_is_rejected(client):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    (session_dir(client, session) / "00000000.part").unlink()
    assert send(client, session).status_code == 409
    assert send(client, session, index="1").status_code == 409
    assert not client.uploaded


@pytest.mark.parametrize("state", [[], {}, {"chunks": []}, {"chunks": {"0": {"size": -1}}}])
def test_corrupt_manifest_is_rejected(client, state):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    manifest = session_dir(client, session) / "session.json"
    if isinstance(state, dict):
        state["metadata"] = json.loads(manifest.read_text())["metadata"]
    manifest.write_text(json.dumps(state))
    assert send(client, session, index="1").status_code == 409


def test_legacy_public_chunks_are_not_touched(client):
    legacy = client.public / ".chunks"
    legacy.mkdir()
    existing = legacy / "keep.part"
    existing.write_bytes(b"legacy")
    assert send(client, count="1").status_code == 200
    assert existing.read_bytes() == b"legacy"


def test_authentication_is_still_required(client, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(routes, "ensure_admin_user", AsyncMock(side_effect=HTTPException(401, "Login required")))
    assert send(client).status_code == 401
    assert not (client.tmp / "storage").exists()


def test_namespace_limit(client, monkeypatch):
    monkeypatch.setattr(routes, "CHUNK_MAX_USERS", 1)
    assert send(client).status_code == 200
    client.user.id = "admin-b"
    assert send(client).status_code == 429


def test_modified_part_is_never_assembled(client):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    (session_dir(client, session) / "00000000.part").write_bytes(b"tampered")
    assert send(client, session, index="1").status_code == 409
    assert not client.uploaded
    assert not (session_dir(client, session) / "assembled.upload").exists()


def test_symlink_part_is_rejected_without_deleting_target(client):
    session = str(uuid4())
    assert send(client, session).status_code == 200
    target = client.tmp / "keep.txt"
    target.write_bytes(b"keep")
    link = session_dir(client, session) / "00000001.part"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this host")
    assert send(client, session, index="1").status_code == 409
    assert target.read_bytes() == b"keep"
    assert link.is_symlink()
