PDF_BYTES = b"%PDF-1.4\n%fake pdf content for testing\n%%EOF"


def _grant_ragchatbot(client, admin_headers, user_id):
    resp = client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"projects": ["ragchatbot"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def _fake_ingest(monkeypatch, text="hello world", chunk_count=1):
    import app.utils.ingest_files as ingest_files_module

    monkeypatch.setattr(
        ingest_files_module,
        "ingest_files",
        lambda file_paths, user_id, pii_entities=None: {
            "passed": True,
            "message": f"Document ingested successfully. Total chunks: {chunk_count}",
            "pii_event": {"check": "pii_masking", "passed": True, "reason": None, "pii_detected": []},
            "chunk_count": chunk_count,
            "extracted_text": text,
        },
    )


def test_ingest_creates_a_document_record_owned_by_the_uploader(client, admin_headers, monkeypatch):
    _fake_ingest(monkeypatch, text="secret warranty terms", chunk_count=2)

    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("terms.pdf", PDF_BYTES, "application/pdf")},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    document_id = resp.json()["document_id"]

    listing = client.get("/api/v1/documents", headers=admin_headers)
    assert listing.status_code == 200
    assert any(d["id"] == document_id for d in listing.json())

    detail = client.get(f"/api/v1/documents/{document_id}", headers=admin_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["filename"] == "terms.pdf"
    assert body["extracted_text"] == "secret warranty terms"
    assert body["chunk_count"] == 2


def test_user_only_sees_their_own_documents(client, admin_headers, user_headers, user_id, monkeypatch):
    _fake_ingest(monkeypatch)
    _grant_ragchatbot(client, admin_headers, user_id)

    # Admin ingests one document, the regular user ingests another.
    client.post("/api/v1/ingest", files={"file": ("admin-doc.pdf", PDF_BYTES, "application/pdf")}, headers=admin_headers)
    client.post("/api/v1/ingest", files={"file": ("user-doc.pdf", PDF_BYTES, "application/pdf")}, headers=user_headers)

    user_listing = client.get("/api/v1/documents", headers=user_headers)
    assert user_listing.status_code == 200
    filenames = {d["filename"] for d in user_listing.json()}
    assert filenames == {"user-doc.pdf"}
    assert all(d["uploaded_by"] is None for d in user_listing.json())


def test_admin_sees_every_users_documents_with_uploader(client, admin_headers, user_headers, user_id, monkeypatch):
    _fake_ingest(monkeypatch)
    _grant_ragchatbot(client, admin_headers, user_id)

    client.post("/api/v1/ingest", files={"file": ("admin-doc.pdf", PDF_BYTES, "application/pdf")}, headers=admin_headers)
    client.post("/api/v1/ingest", files={"file": ("user-doc.pdf", PDF_BYTES, "application/pdf")}, headers=user_headers)

    admin_listing = client.get("/api/v1/documents", headers=admin_headers)
    assert admin_listing.status_code == 200
    by_filename = {d["filename"]: d["uploaded_by"] for d in admin_listing.json()}
    assert set(by_filename) == {"admin-doc.pdf", "user-doc.pdf"}
    assert by_filename["user-doc.pdf"] == "alice@example.com"


def test_user_cannot_view_another_users_document_detail(client, admin_headers, user_headers, user_id, monkeypatch):
    _fake_ingest(monkeypatch)
    _grant_ragchatbot(client, admin_headers, user_id)

    admin_ingest = client.post(
        "/api/v1/ingest", files={"file": ("admin-only.pdf", PDF_BYTES, "application/pdf")}, headers=admin_headers
    )
    document_id = admin_ingest.json()["document_id"]

    resp = client.get(f"/api/v1/documents/{document_id}", headers=user_headers)
    assert resp.status_code == 404


def test_documents_endpoint_requires_ragchatbot_access(client, user_headers):
    resp = client.get("/api/v1/documents", headers=user_headers)
    assert resp.status_code == 403


def test_unknown_document_id_is_404(client, admin_headers):
    resp = client.get("/api/v1/documents/does-not-exist", headers=admin_headers)
    assert resp.status_code == 404


def test_documents_status_is_false_when_nothing_ingested(client, admin_headers):
    resp = client.get("/api/v1/documents/status", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"has_documents": False}


def test_documents_status_is_true_after_any_ingestion(client, admin_headers, monkeypatch):
    _fake_ingest(monkeypatch)
    client.post("/api/v1/ingest", files={"file": ("a.pdf", PDF_BYTES, "application/pdf")}, headers=admin_headers)

    resp = client.get("/api/v1/documents/status", headers=admin_headers)
    assert resp.json() == {"has_documents": True}


def test_documents_status_is_scoped_to_the_caller_not_global(client, admin_headers, user_headers, user_id, monkeypatch):
    '''A user with zero uploads of their own must see has_documents=False even if
    someone else has ingested plenty - chat retrieval only ever draws from this
    user's own documents (never another user's, not even an admin's), so the
    disclaimer it drives has to answer the same per-user question.'''
    _fake_ingest(monkeypatch)
    _grant_ragchatbot(client, admin_headers, user_id)
    client.post("/api/v1/ingest", files={"file": ("admin-doc.pdf", PDF_BYTES, "application/pdf")}, headers=admin_headers)

    resp = client.get("/api/v1/documents/status", headers=user_headers)
    assert resp.json() == {"has_documents": False}

    own_upload = client.get("/api/v1/documents/status", headers=admin_headers)
    assert own_upload.json() == {"has_documents": True}
