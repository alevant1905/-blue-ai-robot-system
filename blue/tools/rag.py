"""
Blue Robot Local RAG System
============================
ChromaDB-based document retrieval for PDF and text documents.
Uses ChromaDB's built-in embedding model (all-MiniLM-L6-v2 via onnxruntime).
"""

import hashlib
import os
import threading
from typing import Dict, List

CHROMA_DB_PATH = os.environ.get(
    "CHROMA_DB_PATH", os.path.join(os.getcwd(), "data", "chromadb")
)
COLLECTION_NAME = "blue_documents"
CHUNK_SIZE = 800  # characters per chunk
CHUNK_OVERLAP = 200  # overlap between chunks

# Lazy-initialized globals
_chroma_client = None
_collection = None

# Serializes every ChromaDB write. ChromaDB's SQLite writer lock has no
# timeout, so two threads indexing at once (the web upload handler and the
# documents-folder watcher) deadlock and hang the upload request forever.
_write_lock = threading.RLock()


def _get_collection():
    """Lazy-init ChromaDB client and collection."""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection

    with _write_lock:
        if _collection is not None:
            return _collection
        try:
            import chromadb
            from chromadb.config import Settings

            os.makedirs(CHROMA_DB_PATH, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(
                path=CHROMA_DB_PATH,
                settings=Settings(anonymized_telemetry=False),
            )
            _collection = _chroma_client.get_or_create_collection(
                name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
            )
            print(f"   [RAG] ChromaDB initialized ({_collection.count()} chunks indexed)")
            return _collection
        except ImportError:
            print("   [RAG] ChromaDB not installed. Run: pip install chromadb")
            return None
        except Exception as e:
            print(f"   [RAG] Error initializing ChromaDB: {e}")
            return None


def chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> List[str]:
    """Split text into overlapping chunks at paragraph/sentence boundaries."""
    if not text or not text.strip():
        return []

    if len(text) <= chunk_size:
        return [text.strip()]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())

            # If paragraph itself is too long, split by sentences
            if len(para) > chunk_size:
                words = para.split()
                current_chunk = ""
                for word in words:
                    if len(current_chunk) + len(word) + 1 <= chunk_size:
                        current_chunk = (
                            current_chunk + " " + word if current_chunk else word
                        )
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = word
            else:
                current_chunk = para

    if current_chunk and current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Add overlap: prepend last N chars of previous chunk to give context
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            # Find a word boundary in the overlap to avoid cutting mid-word
            space_idx = prev_tail.find(" ")
            if space_idx > 0:
                prev_tail = prev_tail[space_idx + 1 :]
            overlapped.append(prev_tail + " " + chunks[i])
        chunks = overlapped

    return chunks


def _get_file_hash(filepath: str) -> str:
    """Get MD5 hash of file for document ID."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def index_document(filepath: str, filename: str, doc_id: str = None,
                   text: str = None, folder: str = "") -> Dict:
    """Extract text from a document and add its chunks to ChromaDB.

    If `text` is provided, skip extraction — callers that already extracted
    can pass it in to avoid a second PyPDF2 pass on large files.

    `folder` is the document's library folder (POSIX rel path, "" for root).
    It's stored on every chunk so retrieval can be scoped to an area of
    expertise (e.g. only "Publications" or only "Courses/CS240").
    """
    collection = _get_collection()
    if collection is None:
        return {"success": False, "error": "ChromaDB not available"}

    if text is None:
        # Subprocess-isolated: pypdf access violations must not kill the
        # server (it happened twice on 2026-07-04 during batch reindexing).
        from blue.tools.documents import extract_text_isolated
        text = extract_text_isolated(filepath)

    if text.startswith("Error"):
        return {"success": False, "error": text}

    if not text.strip():
        return {"success": False, "error": "No text content extracted"}

    # Generate doc_id from file hash if not provided
    if not doc_id:
        doc_id = _get_file_hash(filepath)

    # Chunk the text (CPU-only, no DB access — kept outside the write lock).
    chunks = chunk_text(text)
    if not chunks:
        return {"success": False, "error": "No chunks generated from text"}

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "doc_id": doc_id,
            "filename": filename,
            "filepath": str(filepath),
            "folder": folder or "",
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]

    # Serialize the actual ChromaDB writes so a concurrent indexer (the
    # folder watcher) can't deadlock against this one on the SQLite lock.
    with _write_lock:
        # Remove existing chunks for this document (handles re-indexing).
        try:
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
                print(f"   [RAG] Removed {len(existing['ids'])} old chunks for {filename}")
        except Exception:
            pass

        # Batch the add() so huge documents emit progress instead of looking hung.
        batch_size = 128
        total = len(chunks)
        for i in range(0, total, batch_size):
            end = min(i + batch_size, total)
            collection.add(
                documents=chunks[i:end],
                ids=ids[i:end],
                metadatas=metadatas[i:end],
            )
            if total > batch_size:
                print(f"   [RAG] embedded {end}/{total} chunks of {filename}", flush=True)

    print(f"   [RAG] Indexed {len(chunks)} chunks for {filename}")
    return {
        "success": True,
        "chunks_indexed": len(chunks),
        "doc_id": doc_id,
        "filename": filename,
    }


def remove_document(doc_id: str) -> bool:
    """Remove a document and all its chunks from the index."""
    collection = _get_collection()
    if collection is None:
        return False
    try:
        with _write_lock:
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
                print(f"   [RAG] Removed {len(existing['ids'])} chunks for doc {doc_id}")
        return True
    except Exception as e:
        print(f"   [RAG] Error removing document: {e}")
        return False


def _folder_where(folders):
    """Build a ChromaDB metadata filter that scopes a query to one or more
    library folders, or None for no scoping."""
    if not folders:
        return None
    fl = [f for f in folders if f is not None]
    if not fl:
        return None
    if len(fl) == 1:
        return {"folder": fl[0]}
    return {"folder": {"$in": fl}}


def search(query: str, max_results: int = 3, folders=None) -> List[Dict]:
    """Semantic search across indexed documents.

    `folders` (optional list of POSIX rel paths) scopes the search to those
    library folders — used for expertise-area queries.

    Returns list of dicts with keys: filename, filepath, folder, content,
    score, chunk_index, total_chunks
    """
    collection = _get_collection()
    if collection is None:
        return []

    if collection.count() == 0:
        return []

    try:
        where = _folder_where(folders)
        # Request extra results so we can deduplicate by document
        n_results = min(max_results * 3, collection.count())
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        if (
            not results
            or not results["documents"]
            or not results["documents"][0]
        ):
            return []

        # Deduplicate: keep best chunk per document
        seen_docs = {}
        for doc_text, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            fname = meta["filename"]
            score = 1.0 - dist  # cosine distance -> similarity
            if fname not in seen_docs or score > seen_docs[fname]["score"]:
                seen_docs[fname] = {
                    "filename": fname,
                    "filepath": meta["filepath"],
                    "folder": meta.get("folder", ""),
                    "content": doc_text,
                    "score": score,
                    "chunk_index": meta["chunk_index"],
                    "total_chunks": meta["total_chunks"],
                }

        # Sort by score descending, return top N
        ranked = sorted(seen_docs.values(), key=lambda x: x["score"], reverse=True)
        return ranked[:max_results]

    except Exception as e:
        print(f"   [RAG] Search error: {e}")
        return []


def _filename_where(filenames):
    """ChromaDB metadata filter scoping a query to specific documents (by
    filename), or None for no scoping."""
    fl = [f for f in (filenames or []) if f]
    if not fl:
        return None
    return {"filename": fl[0]} if len(fl) == 1 else {"filename": {"$in": fl}}


def search_in_documents(query: str, filenames, max_results: int = 6) -> List[Dict]:
    """Semantic search scoped to specific library documents (by filename).

    Unlike search(), this does NOT deduplicate to one chunk per document, so a
    single selected document can contribute several relevant passages. Returns
    up to max_results chunks, each: filename, filepath, folder, content, score,
    chunk_index, total_chunks."""
    collection = _get_collection()
    if collection is None or collection.count() == 0:
        return []
    where = _filename_where(filenames)
    if where is None:
        return []
    try:
        n_results = min(max(int(max_results), 1), collection.count())
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        if not results or not results.get("documents") or not results["documents"][0]:
            return []
        out = []
        for doc_text, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            out.append({
                "filename": meta.get("filename", ""),
                "filepath": meta.get("filepath", ""),
                "folder": meta.get("folder", ""),
                "content": doc_text,
                "score": 1.0 - dist,
                "chunk_index": meta.get("chunk_index"),
                "total_chunks": meta.get("total_chunks"),
            })
        return out
    except Exception as e:
        print(f"   [RAG] search_in_documents error: {e}")
        return []


def search_expertise(
    query: str, max_chunks: int = 8, max_per_doc: int = 3, folders=None
) -> List[Dict]:
    """Multi-chunk semantic search for expertise-style queries.

    Unlike `search()`, which deduplicates to one chunk per document (good
    for "what's in my contract" style lookups), this returns up to
    `max_chunks` total chunks across multiple documents — capped at
    `max_per_doc` per document so a single long file can't dominate.

    Useful for "what does the literature say about X" / "summarise what we
    know about Y" queries where you want richer cross-document coverage
    AND multiple passages from the most-relevant single document.

    Each result dict has the same shape as `search()`: filename, filepath,
    content, score, chunk_index, total_chunks.
    """
    collection = _get_collection()
    if collection is None or collection.count() == 0:
        return []

    try:
        where = _folder_where(folders)
        # Over-fetch so we can group, dedupe near-identical chunks, and cap
        # per-document. Want roughly max_chunks * max_per_doc to be safe.
        n_results = min(max_chunks * max_per_doc, collection.count())
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        if not results or not results["documents"] or not results["documents"][0]:
            return []

        per_doc_count: Dict[str, int] = {}
        ranked: List[Dict] = []
        seen_signatures: set = set()
        for doc_text, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            fname = meta["filename"]
            # Cap chunks-per-doc to keep coverage broad.
            if per_doc_count.get(fname, 0) >= max_per_doc:
                continue
            # Drop near-identical chunks (same first 80 chars) — chunk
            # overlap can produce strong but redundant results.
            sig = (fname, (doc_text or "")[:80])
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            per_doc_count[fname] = per_doc_count.get(fname, 0) + 1
            ranked.append({
                "filename": fname,
                "filepath": meta["filepath"],
                "folder": meta.get("folder", ""),
                "content": doc_text,
                "score": 1.0 - dist,
                "chunk_index": meta.get("chunk_index"),
                "total_chunks": meta.get("total_chunks"),
            })
            if len(ranked) >= max_chunks:
                break

        # Sort the kept chunks by score so the strongest ones appear first.
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    except Exception as e:
        print(f"   [RAG] Expertise search error: {e}")
        return []


def index_all_documents(documents_folder: str) -> Dict:
    """Batch index all text/PDF documents in the given folder."""
    results = {"indexed": 0, "failed": 0, "skipped": 0, "errors": []}

    text_extensions = {".pdf", ".txt", ".md", ".doc", ".docx", ".csv", ".rtf", ".html"}

    if not os.path.isdir(documents_folder):
        results["errors"].append(f"Folder not found: {documents_folder}")
        return results

    base = os.path.abspath(documents_folder)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        rel = os.path.relpath(root, base)
        folder = "" if rel == "." else rel.replace("\\", "/")
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in text_extensions:
                results["skipped"] += 1
                continue

            filepath = os.path.join(root, filename)
            if not os.path.isfile(filepath):
                results["skipped"] += 1
                continue

            result = index_document(filepath, filename, folder=folder)

            if result.get("success"):
                results["indexed"] += 1
                print(f"   [RAG] OK: {filename} ({result['chunks_indexed']} chunks) [{folder or 'root'}]")
            else:
                results["failed"] += 1
                error_msg = f"{filename}: {result.get('error', 'unknown')}"
                results["errors"].append(error_msg)
                print(f"   [RAG] FAIL: {error_msg}")

    return results


def get_stats() -> Dict:
    """Get RAG index statistics."""
    collection = _get_collection()
    if collection is None:
        return {"available": False, "error": "ChromaDB not available"}

    count = collection.count()

    # Get unique document count
    unique_docs = set()
    if count > 0:
        try:
            all_meta = collection.get(include=["metadatas"])
            for meta in all_meta.get("metadatas", []):
                if meta:
                    unique_docs.add(meta.get("filename", "unknown"))
        except Exception:
            pass

    return {
        "available": True,
        "total_chunks": count,
        "total_documents": len(unique_docs),
        "document_names": sorted(unique_docs),
        "db_path": CHROMA_DB_PATH,
    }
