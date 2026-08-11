import os
import fitz
import pandas as pd

from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_community.embeddings import HuggingFaceEmbeddings
from streamlit import pdf
import torch
from app.utils.mongo import get_mongo_client, create_vector_search_index
import io
from PIL import Image
from paddleocr import PaddleOCR
from app.core.ingest_guardrails import scan_ingested_pii
from app.core.logger import get_logger

logger = get_logger(__name__)

ocr = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang="en"
)

device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
embedding_model = HuggingFaceEmbeddings(
    model_name="BAAI/bge-m3",
    model_kwargs={"device": device},
    encode_kwargs={"normalize_embeddings": True},
)

def extract_images(pdf: fitz.Document, pdf_path: str):

    docs = []

    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]

    image_dir = os.path.join(
        "app",
        "extracted_images",
        pdf_name,
    )

    os.makedirs(image_dir, exist_ok=True)

    for page_no, page in enumerate(pdf, start=1):

        images = page.get_images(full=True)

        if not images:
            continue

        page_text = page.get_text("text")

        for img_index, img in enumerate(images):

            xref = img[0]

            base_image = pdf.extract_image(xref)

            image_bytes = base_image["image"]

            ext = base_image["ext"]

            image_name = f"page_{page_no}_img_{img_index}.{ext}"

            image_path = os.path.join(image_dir, image_name)

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            # OCR
            ocr_text = ""

            try:

                result = ocr.predict(image_path)

                if result:

                    texts = []

                    for res in result:

                        if "rec_texts" in res:

                            texts.extend(res["rec_texts"])

                    ocr_text = "\n".join(texts)

            except Exception as e:
                logger.exception("OCR failed on '%s': %s", image_path, e)

            docs.append(
                Document(
                    page_content=f"""
                                Page Text:
                                {page_text}

                                Image OCR:
                                {ocr_text}
                                """,
                    metadata={
                        "source": os.path.basename(pdf_path),
                        "page": page_no,
                        "sheet_name": "",
                        "content_type": "pdf_image",
                        "image_path": image_path,
                    },
                )
            )

    return docs


def load_pdf(pdf_path: str) -> List[Document]:
    docs = []
    pdf = fitz.open(pdf_path)

    image_docs = extract_images(pdf, pdf_path)

    for page_no, page in enumerate(pdf, start=1):
        text = page.get_text("text")

        if text.strip():
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": os.path.basename(pdf_path),
                        "page": page_no,
                        "sheet_name": "",
                        "content_type": "pdf_text",
                    },
                )
            )

        try:
            tables = page.find_tables()
            for table in tables:
                table_data = table.extract()
                table_text = "\n".join(
                    [
                        " | ".join([str(cell) if cell else "" for cell in row])
                        for row in table_data
                    ]
                )

                if table_text.strip():
                    docs.append(
                        Document(
                            page_content=table_text,
                            metadata={
                                "source": os.path.basename(pdf_path),
                                "page": page_no,
                                "sheet_name": "",
                                "content_type": "pdf_table",
                            },
                        )
                    )
        except Exception as e:
            logger.exception("Failed to extract tables from page %s of '%s': %s", page_no, pdf_path, e)

    docs.extend(image_docs)

    return docs


def load_xlsx(xlsx_path: str) -> List[Document]:
    docs = []
    sheets = pd.read_excel(xlsx_path, sheet_name=None)

    for sheet_name, df in sheets.items():
        text = df.to_markdown(index=False)

        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source": os.path.basename(xlsx_path),
                    "page": 0,
                    "sheet_name": sheet_name,
                    "content_type": "xlsx_table",
                },
            )
        )

    return docs


def ingest_files(file_paths: List[str], collection_name: str):
    try:
        logger.info("Starting ingestion of %d file(s) into collection '%s'", len(file_paths), collection_name)
        all_docs = []

        for path in file_paths:
            if path.lower().endswith(".pdf"):
                all_docs.extend(load_pdf(path))
            elif path.lower().endswith(".xlsx"):
                all_docs.extend(load_xlsx(path))

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=200,
            separators=[
                "\n\n",
                "\n",
                ". ",
                " ",
                ""
            ]
        )

        chunks = splitter.split_documents(all_docs)

        pii_event = scan_ingested_pii(chunks)

        client = get_mongo_client()
        collection = client["rag_database"][collection_name]

        vectorstore = MongoDBAtlasVectorSearch.from_documents(
            documents=chunks,
            embedding=embedding_model,
            collection=collection,
            index_name="default",
        )

        create_vector_search_index(collection_name)

        logger.info("Ingestion completed for collection '%s'. Total chunks: %d", collection_name, len(chunks))

        return {
            "passed": True,
            "message": f"Document Ingested Successfully. Total chunks: {len(chunks)}",
            "pii_event": pii_event,
        }

    except Exception as e:
        logger.exception("Error during ingestion into collection '%s': %s", collection_name, e)
        return {"passed": False, "error": str(e)}