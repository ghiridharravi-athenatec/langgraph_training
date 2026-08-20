from typing import Dict, List

from langchain_core.documents import Document

# Headroom under ingest_files.py's shared RecursiveCharacterTextSplitter's
# chunk_size=700 - table-derived chunks built here bypass that splitter
# entirely (see ingest_files.py), so this budget is the only size control
# they get. Left intentionally below 700 so an occasional oversized row
# doesn't push a chunk past what the rest of the pipeline expects.
_DEFAULT_CHAR_BUDGET = 600


def chunk_table_rows(
    header_lines: List[str], row_lines: List[str], metadata: Dict, char_budget: int = _DEFAULT_CHAR_BUDGET,
) -> List[Document]:
    '''Splits a table into row-batches, repeating header_lines (column names - and,
    for a markdown table, the separator line too) in every batch, instead of the
    generic character-count splitter's behavior of cutting mid-table and leaving every
    chunk after the first with no column-name context at all. Always keeps at least
    one data row per chunk even if that row alone exceeds char_budget, rather than
    dropping it or looping forever trying to make it fit.'''
    header_block = "\n".join(header_lines)

    if not row_lines:
        return [Document(page_content=header_block, metadata=dict(metadata))] if header_block.strip() else []

    chunks = []
    current_rows: List[str] = []
    current_len = len(header_block)

    for row in row_lines:
        row_len = len(row) + 1  # +1 for the newline joining it to the block
        if current_rows and current_len + row_len > char_budget:
            chunks.append(Document(page_content="\n".join([header_block] + current_rows), metadata=dict(metadata)))
            current_rows = []
            current_len = len(header_block)
        current_rows.append(row)
        current_len += row_len

    if current_rows:
        chunks.append(Document(page_content="\n".join([header_block] + current_rows), metadata=dict(metadata)))

    return chunks
