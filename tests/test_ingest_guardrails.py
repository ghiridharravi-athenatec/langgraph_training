PDF_BYTES = b"%PDF-1.4\n%fake pdf content for testing\n%%EOF"


def test_ingest_rejects_wrong_extension(client, admin_headers):
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        params={"collection_name": "warranty"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"]


def test_ingest_rejects_content_not_matching_extension(client, admin_headers):
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("fake.pdf", b"this is not really a pdf", "application/pdf")},
        params={"collection_name": "warranty"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_ingest_rejects_oversized_file(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.core.config.MAX_UPLOAD_SIZE_MB", 0)  # anything is "too big" now
    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("small.pdf", PDF_BYTES, "application/pdf")},
        params={"collection_name": "warranty"},
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

    def fake_ingest_files(file_paths, collection_name):
        return {
            "passed": True,
            "message": "Document Ingested Successfully. Total chunks: 3",
            "pii_event": {"check": "pii_masking", "passed": True, "reason": None, "pii_detected": []},
        }

    monkeypatch.setattr(ingest_files_module, "ingest_files", fake_ingest_files)

    resp = client.post(
        "/api/v1/ingest",
        files={"file": ("small.pdf", PDF_BYTES, "application/pdf")},
        params={"collection_name": "warranty"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["guardrails"]["file_type"]["passed"] is True
    assert body["guardrails"]["file_size"]["passed"] is True
    assert body["guardrails"]["pii_masking"]["passed"] is True
