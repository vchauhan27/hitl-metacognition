import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma

import config

# ---------------------------------------------------------
# Environment & Paths
# ---------------------------------------------------------

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
NOTES_PATH = Path(config.NOTES_FILE)

# ---------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------

def main():
    print("=" * 70)
    print("PERSONAL ASSISTANT - DOCUMENT INGESTION")
    print("=" * 70)

    # -----------------------------------------------------
    # 1. Load notes
    # -----------------------------------------------------

    if not NOTES_PATH.exists():
        raise RuntimeError(f"Notes file not found: {NOTES_PATH}")

    print(f"Loading: {NOTES_PATH.name}")
    text = NOTES_PATH.read_text(encoding="utf-8")
    
    # Split by double newline, ignore comments
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and not p.lstrip().startswith("#")]
    
    documents = [
        Document(page_content=p, metadata={"source": NOTES_PATH.name})
        for p in paragraphs
    ]

    print(f"\nLoaded notes: {len(documents)}")

    if not documents:
        raise RuntimeError("No documents found to ingest.")

    # -----------------------------------------------------
    # 2. Embeddings
    # -----------------------------------------------------

    print("\nInitializing embeddings...")
    embeddings = config.get_embeddings()

    # -----------------------------------------------------
    # 3. Create Chroma vector store
    # -----------------------------------------------------

    print("\nCreating Chroma vector store...")
    
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=config.CHROMA_DIR,
        collection_name=config.CHROMA_COLLECTION,
    )

    # -----------------------------------------------------
    # 4. Verify retrieval
    # -----------------------------------------------------

    print("\nTesting retrieval...")
    results = vectorstore.similarity_search("Sam Carter", k=1)
    
    print(f"Retrieved documents: {len(results)}")
    for i, document in enumerate(results, start=1):
        print(f"\n--- Retrieved document {i} ---")
        print(document.page_content[:200])

    print("\n" + "=" * 70)
    print("INGESTION SUCCESSFUL")
    print("=" * 70)

if __name__ == "__main__":
    main()
