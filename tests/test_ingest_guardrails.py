PDF_BYTES = b"%PDF-1.4\n%fake pdf content for testing\n%%EOF"


def test_ingest_rejects_unsupported_extension(client, admin_headers):
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("notes.exe", b"hello", "application/octet-stream")},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"]


def test_ingest_rejects_content_not_matching_extension(client, admin_headers):
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("fake.pdf", b"this is not really a pdf", "application/pdf")},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_ingest_accepts_plain_text_files(client, admin_headers, monkeypatch):
    import app.utils.ingest_files as ingest_files_module

    def fake_ingest_files(file_paths, user_id):
        return {
            "passed": True,
            "message": "Document ingested successfully. Total chunks: 1",
            "pii_event": {"check": "pii_masking", "passed": True, "reason": None, "pii_detected": []},
            "chunk_count": 1,
            "extracted_text": "hello world",
        }

    monkeypatch.setattr(ingest_files_module, "ingest_files", fake_ingest_files)

    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["guardrails"]["file_type"]["passed"] is True


def test_ingest_rejects_non_utf8_text_file(client, admin_headers):
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("notes.txt", b"\xff\xfe not valid utf-8", "text/plain")},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "UTF-8" in resp.json()["detail"]


def test_ingest_rejects_oversized_file(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.config.MAX_UPLOAD_SIZE_MB", 0)  # anything is "too big" now
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("small.pdf", PDF_BYTES, "application/pdf")},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "exceeds" in resp.json()["detail"]


def test_ingest_valid_pdf_passes_type_and_size_checks(client, admin_headers, monkeypatch):
    # The heavy OCR/embedding/vector-store pipeline is out of scope here - only the
    # guardrail gate (type/size/PII) is under test, same spirit as monkeypatching
    # IntentClassifier.classify_intent in the chat guardrail tests. ingest_files is
    # imported locally inside the route, so patch the module it's imported from.
    import app.utils.ingest_files as ingest_files_module

    def fake_ingest_files(file_paths, user_id):
        return {
            "passed": True,
            "message": "Document ingested successfully. Total chunks: 3",
            "pii_event": {"check": "pii_masking", "passed": True, "reason": None, "pii_detected": []},
            "chunk_count": 3,
            "extracted_text": "chunk one\n\nchunk two\n\nchunk three",
        }

    monkeypatch.setattr(ingest_files_module, "ingest_files", fake_ingest_files)

    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("small.pdf", PDF_BYTES, "application/pdf")},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["guardrails"]["file_type"]["passed"] is True
    assert body["guardrails"]["file_size"]["passed"] is True
    assert body["guardrails"]["pii_masking"]["passed"] is True
    assert body["chunk_count"] == 3
    assert "document_id" in body
