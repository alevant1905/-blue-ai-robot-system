"""
One-time migration: separate camera images from documents into dedicated folders.
Run this once: python migrate_folders.py
"""
import json
import os
import shutil


def migrate():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    index_file = os.path.join(base_dir, "document_index.json")

    # Create new folders
    camera_dir = os.path.join(base_dir, "camera_captures")
    documents_dir = os.path.join(base_dir, "documents")
    uploads_dir = os.path.join(base_dir, "uploads")
    os.makedirs(camera_dir, exist_ok=True)
    os.makedirs(documents_dir, exist_ok=True)
    os.makedirs(uploads_dir, exist_ok=True)

    # Load index
    if not os.path.exists(index_file):
        print("No document_index.json found. Nothing to migrate.")
        return

    with open(index_file, "r") as f:
        index = json.load(f)

    documents = index.get("documents", [])
    updated = []

    for doc in documents:
        old_path = doc.get("filepath", "")
        filename = doc.get("filename", "")

        # Resolve relative paths
        if not os.path.isabs(old_path):
            old_path = os.path.join(base_dir, old_path)

        # Determine destination folder
        if doc.get("camera_capture"):
            new_dir = camera_dir
            doc["doc_type"] = "camera"
        elif filename.lower().endswith((".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".rtf", ".html", ".pptx", ".xlsx")):
            new_dir = documents_dir
            doc["doc_type"] = "document"
        else:
            new_dir = uploads_dir
            doc["doc_type"] = "upload"

        new_path = os.path.join(new_dir, filename)

        # Move file if it exists and isn't already in the right place
        if os.path.exists(old_path):
            if os.path.normpath(old_path) != os.path.normpath(new_path):
                shutil.move(old_path, new_path)
                print(f"MOVED: {old_path} -> {new_path}")
            else:
                print(f"OK (already in place): {filename}")
            doc["filepath"] = new_path
        else:
            print(f"SKIP (file missing): {old_path}")
            doc["filepath"] = new_path  # Update path anyway for consistency

        updated.append(doc)

    index["documents"] = updated

    # Save updated index
    with open(index_file, "w") as f:
        json.dump(index, f, indent=2)

    print(f"\nMigration complete. {len(updated)} entries updated.")
    print(f"  Camera captures -> {camera_dir}")
    print(f"  Documents       -> {documents_dir}")
    print(f"  Other uploads   -> {uploads_dir}")


if __name__ == "__main__":
    migrate()
