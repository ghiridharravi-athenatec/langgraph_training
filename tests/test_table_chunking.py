from app.utils.table_chunking import chunk_table_rows


def test_header_repeated_in_every_chunk():
    header = ["| Task | Assigned To |", "|:---|:---|"]
    rows = [f"| Task {i} | Person {i} |" for i in range(1, 30)]

    chunks = chunk_table_rows(header, rows, metadata={"source": "wide.xlsx"}, char_budget=200)

    assert len(chunks) > 1  # actually needed to split for this to be a meaningful test
    for chunk in chunks:
        assert chunk.page_content.startswith("| Task | Assigned To |\n|:---|:---|")


def test_no_row_is_dropped_or_duplicated():
    header = ["| A | B |"]
    rows = [f"| {i} | x |" for i in range(1, 51)]

    chunks = chunk_table_rows(header, rows, metadata={"source": "wide.xlsx"}, char_budget=100)

    all_rows_seen = "\n".join(c.page_content for c in chunks)
    for row in rows:
        assert all_rows_seen.count(row) == 1


def test_oversized_single_row_still_gets_its_own_chunk():
    header = ["| A |"]
    huge_row = "| " + ("x" * 5000) + " |"

    chunks = chunk_table_rows(header, [huge_row], metadata={}, char_budget=100)

    assert len(chunks) == 1
    assert huge_row in chunks[0].page_content


def test_no_rows_returns_header_only_chunk():
    chunks = chunk_table_rows(["| A | B |"], [], metadata={"source": "empty.xlsx"})
    assert len(chunks) == 1
    assert chunks[0].page_content == "| A | B |"


def test_empty_header_and_rows_returns_nothing():
    assert chunk_table_rows([""], [], metadata={}) == []


def test_metadata_is_copied_not_shared():
    metadata = {"source": "a.xlsx"}
    chunks = chunk_table_rows(["h"], ["r1", "r2"], metadata=metadata, char_budget=1)

    assert len(chunks) == 2
    chunks[0].metadata["source"] = "mutated"
    assert chunks[1].metadata["source"] == "a.xlsx"
    assert metadata["source"] == "a.xlsx"
