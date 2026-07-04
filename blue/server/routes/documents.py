"""Document library + upload routes, extracted verbatim from bluetools.py.

register(app): the /documents library GUI + /api/library/list (registered
at the original pre-__main__ position). register_uploads(app): the upload
and file-serving routes that originally lived AFTER app.run() in the
__main__ block — bluetools calls this from that same position, so under
`python bluetools.py` they (still) only register once app.run returns,
while under run.py imports everything registers as before.
All shared helpers/state stay in bluetools, read via bt.<name>.
"""
import os
import re

import bluetools as bt
from flask import (Response, jsonify, redirect, render_template_string,
                   request, send_from_directory, url_for)
from werkzeug.utils import secure_filename

from blue.server.pages.documents import DOCUMENT_MANAGER_HTML


def register(app):
    @app.route('/documents', methods=['GET', 'POST'])
    def manage_documents():
        """Folder-aware web interface for the document library."""
        message = None
        message_type = None
        current_folder = bt._safe_rel_folder(request.values.get('folder', '') or request.values.get('parent', ''))

        if request.method == 'POST':
            action = request.form.get('action', 'upload')

            if action == 'create_folder':
                parent = bt._safe_rel_folder(request.form.get('parent', ''))
                name = bt._safe_folder_segment(request.form.get('name', ''))
                current_folder = parent
                if not name:
                    message, message_type = "Please enter a valid folder name.", "error"
                else:
                    rel = f"{parent}/{name}" if parent else name
                    res = bt.create_library_folder(rel)
                    if res.get('success'):
                        message, message_type = f"Created folder '{name}'.", "success"
                    else:
                        message, message_type = f"Couldn't create folder: {res.get('error')}", "error"

            elif 'file' not in request.files or request.files['file'].filename == '':
                message, message_type = "No file selected", "error"
            else:
                file = request.files['file']
                if not bt.allowed_file(file.filename):
                    message = f"Invalid file type. Allowed: {', '.join(bt.ALLOWED_EXTENSIONS)}"
                    message_type = "error"
                else:
                    try:
                        filename = secure_filename(file.filename)
                        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                        text_doc = ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html', 'pptx', 'xlsx')
                        if text_doc:
                            target_dir = bt._abs_library_path(current_folder)
                            os.makedirs(target_dir, exist_ok=True)
                            filepath = os.path.join(target_dir, filename)
                        else:
                            # Images and other non-text uploads stay in bt.UPLOAD_FOLDER.
                            filepath = os.path.join(str(bt.UPLOAD_FOLDER), filename)

                        file.save(filepath)
                        folder = bt._folder_of_filepath(filepath)
                        file_size = os.path.getsize(filepath)
                        file_hash = bt.get_file_hash(filepath)

                        index = bt.load_document_index()
                        duplicate = any(doc.get('hash') == file_hash for doc in index['documents'])

                        if duplicate:
                            message = f"Document '{filename}' already exists (duplicate detected)"
                            message_type = "error"
                            os.remove(filepath)
                        else:
                            text_content = bt.extract_text_from_file(filepath)
                            text_preview = text_content[:500] if not text_content.startswith("Error") else ""

                            doc_entry = {
                                'filename': filename,
                                'filepath': str(filepath),
                                'folder': folder,
                                'size': file_size,
                                'hash': file_hash,
                                'uploaded_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
                                'text_preview': text_preview,
                                'indexed_in_rag': False,
                            }
                            index['documents'].append(doc_entry)
                            bt.save_document_index(index)

                            try:
                                from blue.tools.rag import index_document as rag_index
                                if ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html'):
                                    rag_result = rag_index(
                                        filepath, filename,
                                        doc_id=file_hash, text=text_content, folder=folder,
                                    )
                                    doc_entry['indexed_in_rag'] = rag_result.get('success', False)
                                    if doc_entry['indexed_in_rag']:
                                        print(f"   [RAG] Indexed {rag_result.get('chunks_indexed', 0)} chunks for {filename} [{folder or 'root'}]")
                                    else:
                                        print(f"   [RAG] indexing skipped: {rag_result.get('error')}")
                            except ImportError:
                                print("   [WARN] ChromaDB not installed, skipping local RAG index")
                            except Exception as e:
                                print(f"   [WARN] Local RAG indexing error: {e}")

                            bt.save_document_index(index)
                            where = current_folder if current_folder else "Library root"
                            message = f"Uploaded and indexed '{filename}' into {where}."
                            message_type = "success"

                    except Exception as e:
                        message = f"Error uploading file: {str(e)}"
                        message_type = "error"

        ctx = bt._library_view_context(current_folder, message, message_type)
        return render_template_string(DOCUMENT_MANAGER_HTML, **ctx)


    @app.route('/documents/delete', methods=['POST'])
    def delete_document():
        """Delete one document, identified by folder + filename so files with the
        same name in different folders don't collide."""
        folder = bt._safe_rel_folder(request.form.get('folder', ''))
        filename = request.form.get('filename', '')
        try:
            index = bt.load_document_index()
            documents = index.get('documents', [])
            kept, deleted = [], False
            for doc in documents:
                same_name = doc.get('filename') == filename
                same_folder = bt._safe_rel_folder(doc.get('folder', '')) == folder
                if same_name and same_folder and not deleted:
                    filepath = doc.get('filepath', '')
                    if filepath and os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass
                    try:
                        from blue.tools.rag import remove_document
                        remove_document(doc.get('hash', ''))
                    except Exception:
                        pass
                    deleted = True
                else:
                    kept.append(doc)
            if deleted:
                index['documents'] = kept
                bt.save_document_index(index)
        except Exception as e:
            print(f"Error deleting document: {e}")
        return redirect(url_for('manage_documents', folder=folder))


    @app.route('/documents/folder/delete', methods=['POST'])
    def delete_library_folder():
        """Delete an (empty) library folder. Refuses if it still holds documents
        or subfolders, so files are never silently destroyed."""
        folder = bt._safe_rel_folder(request.form.get('folder', ''))
        back = bt._safe_rel_folder(request.form.get('back', ''))
        full = bt._abs_library_path(folder)
        base = os.path.abspath(bt.DOCUMENTS_FOLDER)
        try:
            if folder and os.path.isdir(full) and os.path.abspath(full) != base:
                if os.listdir(full):
                    # Non-empty (files or subfolders) — don't destroy anything.
                    print(f"   [LIBRARY] refused to delete non-empty folder: {folder}")
                else:
                    os.rmdir(full)
                    print(f"   [LIBRARY] deleted empty folder: {folder}")
        except Exception as e:
            print(f"   [LIBRARY] folder delete error: {e}")
        return redirect(url_for('manage_documents', folder=back))


    @app.route('/documents/download', methods=['GET'])
    def download_document():
        """Download a document, resolved via the index by folder + filename (with
        a legacy fallback that scans the known storage folders)."""
        try:
            from flask import send_file
            folder = bt._safe_rel_folder(request.args.get('folder', ''))
            filename = request.args.get('filename', '')

            filepath = None
            for doc in bt.load_document_index().get('documents', []):
                if (doc.get('filename') == filename
                        and bt._safe_rel_folder(doc.get('folder', '')) == folder):
                    cand = doc.get('filepath', '')
                    if cand and os.path.exists(cand):
                        filepath = cand
                    break

            if not filepath:
                safe = secure_filename(filename)
                for base in [bt._abs_library_path(folder), str(bt.UPLOAD_FOLDER), bt.DOCUMENTS_FOLDER, bt.CAMERA_FOLDER]:
                    candidate = os.path.join(base, safe)
                    if os.path.exists(candidate):
                        filepath = candidate
                        break

            if not filepath:
                return "File not found", 404

            return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

        except Exception as e:
            print(f"Error downloading document: {e}")
            return f"Error: {str(e)}", 500

    @app.route('/api/library/list', methods=['GET'])
    def api_library_list():
        """List library folders + (non-camera) documents for the chat Context
        panel's focus picker. Mirrors the filtering in _build_expertise_block so
        camera captures never show up as pickable 'documents'."""
        try:
            index = bt.load_document_index()
        except Exception:
            index = {"documents": []}
        docs = []
        for d in index.get("documents", []):
            fn = d.get("filename")
            if not fn or d.get("camera_capture") or str(fn).startswith("camera_"):
                continue
            preview = re.sub(r"\s+", " ", (d.get("text_preview") or "")).strip()
            if preview.startswith("[IMAGE FILE"):
                preview = ""
            docs.append({
                "filename": fn,
                "folder": d.get("folder") or "",
                "preview": preview[:120],
            })
        docs.sort(key=lambda x: (x["folder"], x["filename"].lower()))
        try:
            folders = bt.list_library_folders()
        except Exception:
            folders = []
        return jsonify({"folders": folders, "documents": docs})


def register_uploads(app):
    # --- Image Upload Endpoints ---
    @app.route("/upload", methods=["GET", "POST"])


    def upload_page():
        # If POST, handle files directly and then redirect to /documents (if present) or return a simple page.
        if request.method == "POST":
            if "file" not in request.files and "files" not in request.files:
                return Response("No file part in the request.", status=400)
            files = request.files.getlist("file") or request.files.getlist("files")
            saved = []
            for f in files:
                if not f or f.filename == "":
                    continue
                if not bt.allowed_file(f.filename):
                    continue
                target_path = bt.ensure_unique_path(bt.UPLOAD_FOLDER, f.filename)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                f.save(target_path)
                saved.append(os.path.basename(target_path))
            if not saved:
                return Response("No valid image files were uploaded.", status=400)
            # Prefer redirect to a document manager if available
            try:
                return redirect(url_for("documents"))
            except Exception:
                # Fallback simple success page
                body = "<h3>Uploaded:</h3><ul>" + "".join(f"<li>{x}</li>" for x in saved) + "</ul>"
                return Response(body, mimetype="text/html")

        # GET -> simple HTML upload form
        html = _upload_page_html(
            title="Upload images",
            lead="Add photos to Blue's uploads folder.",
            accept='accept="image/*"',
            details=f"<p>Files will be saved under <code>{bt.UPLOAD_FOLDER}</code></p>",
        )
        return Response(html, mimetype="text/html")


    def _upload_page_html(title: str, lead: str, accept: str, details: str) -> str:
        """Shared, design-system-styled shell for the two plain upload forms."""
        return f"""
    <!doctype html>
    <html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — Blue</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <style>
     :root{{ --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
       --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
       --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06); }}
     *{{box-sizing:border-box}}
     body{{font-family:-apple-system,'Segoe UI',sans-serif;background:var(--cream);color:var(--ink);
       margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;line-height:1.55}}
     .card{{background:var(--paper);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);
       padding:28px;max-width:460px;width:100%}}
     h1{{font-size:1.35em;margin:0 0 6px}}
     p.lead{{color:var(--slate);margin:0 0 18px}}
     input[type=file]{{display:block;width:100%;padding:12px;border:1.5px dashed var(--line);
       border-radius:12px;margin-bottom:14px;background:transparent;color:var(--ink)}}
     button.primary{{width:100%;padding:13px;border:none;border-radius:12px;background:#1a2e1a;color:#fff;
       font:inherit;font-weight:600;cursor:pointer}}
     .details{{margin-top:16px;font-size:.85em;color:var(--slate)}}
     .details p{{margin:4px 0;overflow-wrap:anywhere}}
    </style></head><body>
    <div class="card">
      <h1>{title}</h1>
      <p class="lead">{lead}</p>
      <form method="post" enctype="multipart/form-data">
        <input type="file" name="file" multiple {accept}>
        <button class="primary" type="submit">Upload</button>
      </form>
      <div class="details">{details}</div>
    </div>
    </body></html>"""


    @app.route("/api/upload", methods=["POST"])


    def api_upload():
        if "file" not in request.files and "files" not in request.files:
            return jsonify({"error": "No file(s) in request. Use 'file' or 'files' field."}), 400
        files = request.files.getlist("file") or request.files.getlist("files")
        saved = []
        rejected = []
        for f in files:
            if not f or f.filename == "":
                rejected.append({"filename": "", "reason": "empty filename"})
                continue
            if not bt.allowed_file(f.filename):
                rejected.append({"filename": f.filename, "reason": "unsupported extension"})
                continue
            target_path = bt.ensure_unique_path(bt.UPLOAD_FOLDER, f.filename)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            f.save(target_path)
            saved.append({"filename": os.path.basename(target_path), "path": target_path})
        return jsonify({"saved": saved, "rejected": rejected, "upload_folder": bt.UPLOAD_FOLDER})


    # --- Document Upload Endpoints (images + texts, saved into uploaded_documents) ---
    @app.route("/documents/upload", methods=["GET", "POST"])


    def documents_upload():
        if request.method == "POST":
            if "file" not in request.files and "files" not in request.files:
                return Response("No file part in the request.", status=400)
            files = request.files.getlist("file") or request.files.getlist("files")
            saved, duplicates = [], []
            for f in files:
                if not f or f.filename == "":
                    continue
                if not bt.allowed_file(f.filename):
                    continue
                # Route by file type: text/docs to documents/, images to uploads/
                ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else ''
                if ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html', 'pptx', 'xlsx', 'json', 'xml'):
                    target_folder = str(bt.DOCUMENTS_FOLDER)
                else:
                    target_folder = str(bt.UPLOAD_FOLDER)
                path = bt.ensure_unique_path(target_folder, f.filename)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                f.save(path)
                result = bt.register_uploaded_file(path, os.path.basename(path))
                if result.get('duplicate'):
                    duplicates.append(result.get('existing_filename') or f.filename)
                else:
                    saved.append(os.path.basename(path))
            if not saved and not duplicates:
                return Response("No valid files were uploaded.", status=400)
            try:
                return redirect(url_for("documents"))
            except Exception:
                body = "<h3>Uploaded:</h3><ul>" + "".join(f"<li>{x}</li>" for x in saved) + "</ul>"
                if duplicates:
                    body += "<h3>Skipped (duplicates):</h3><ul>" + "".join(f"<li>{x}</li>" for x in duplicates) + "</ul>"
                return Response(body, mimetype="text/html")

        # GET -> HTML form
        html = _upload_page_html(
            title="Upload documents",
            lead="Add documents or images to the library Blue & Hexia read.",
            accept="",
            details=(
                f"<p>Documents saved under <code>{bt.DOCUMENTS_FOLDER}</code></p>"
                f"<p>Images saved under <code>{bt.UPLOAD_FOLDER}</code></p>"
                f"<p>Allowed: {', '.join(sorted(bt.ALLOWED_EXTENSIONS))}</p>"
            ),
        )
        return Response(html, mimetype="text/html")


    @app.route("/api/documents/upload", methods=["POST"])


    def api_documents_upload():
        if "file" not in request.files and "files" not in request.files:
            return jsonify({"error": "No file(s) in request. Use 'file' or 'files' field."}), 400
        files = request.files.getlist("file") or request.files.getlist("files")
        saved, rejected, duplicates = [], [], []
        for f in files:
            if not f or f.filename == "":
                rejected.append({"filename": "", "reason": "empty filename"})
                continue
            if not bt.allowed_file(f.filename):
                rejected.append({"filename": f.filename, "reason": "unsupported extension"})
                continue
            # Route by file type
            ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else ''
            if ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html', 'pptx', 'xlsx', 'json', 'xml'):
                target_folder = str(bt.DOCUMENTS_FOLDER)
            else:
                target_folder = str(bt.UPLOAD_FOLDER)
            path = bt.ensure_unique_path(target_folder, f.filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
            result = bt.register_uploaded_file(path, os.path.basename(path))
            if result.get('duplicate'):
                duplicates.append({"filename": f.filename, "existing": result.get('existing_filename')})
            else:
                saved.append({
                    "filename": os.path.basename(path),
                    "path": path,
                    "indexed_in_rag": result.get('indexed_in_rag', False),
                })
        return jsonify({
            "saved": saved,
            "rejected": rejected,
            "duplicates": duplicates,
            "documents_folder": bt.DOCUMENTS_FOLDER,
        })


    @app.route("/documents/file/<path:filename>")
    def serve_document_file(filename):
        # Check all folders for the file
        for folder in [bt.DOCUMENTS_FOLDER, str(bt.UPLOAD_FOLDER), bt.CAMERA_FOLDER]:
            candidate = os.path.join(folder, filename)
            if os.path.exists(candidate):
                return send_from_directory(folder, filename, as_attachment=False)
        return "File not found", 404
