"""Standalone text-extraction worker.

Run as: python blue/tools/extract_worker.py <filepath>
Prints the extracted text (UTF-8) to stdout.

Extraction runs here, in a throwaway process, because pypdf can die with a
native access violation mid-extraction (it took the whole server down twice
on 2026-07-04, on different PDFs each run). The parent treats a dead worker
as one failed document instead of a dead server.

Deliberately does NOT import the `blue` package — its __init__ pulls in the
memory DB and other live systems. documents.py is loaded by file path.
"""

import importlib.util
import os
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_worker.py <filepath>", file=sys.stderr)
        return 2

    here = os.path.dirname(os.path.abspath(__file__))
    # Running a script from blue/tools puts that directory at sys.path[0],
    # where calendar.py shadows the stdlib calendar that requests needs.
    sys.path[:] = [p for p in sys.path
                   if os.path.abspath(p or os.getcwd()) != here]
    spec = importlib.util.spec_from_file_location(
        "_blue_documents_standalone", os.path.join(here, "documents.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    text = mod.extract_text_from_file(sys.argv[1])
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
