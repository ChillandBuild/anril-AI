"""Read one local file into the knowledge base from the command line (the gated real-book run).

    cd backend
    python -m app.companion.kb.ingest_cli <tenant_id> "Book 7.pdf" --dry-run --pages 1-5
    python -m app.companion.kb.ingest_cli <tenant_id> "Book 7.pdf" --collection "Astrology books" --tier 2

--dry-run   reads the pages through the same functions the real job uses and prints, per page,
            how it was read (text_layer / ocr), how many characters, and how long it took.
            It writes nothing: no upload, no database row. A typed file needs no database at
            all. A scanned page still needs the business's Gemini key (read from the database);
            without it the page is printed as "not read" with the reason, and the run goes on.
--pages     with --dry-run only: "3", "1-5" or "1-5,40,200-210".
--show-text with --dry-run: also print the first 200 characters of each page (to eyeball OCR).
Without --dry-run the file is uploaded, registered in the collection (made if missing) and read
to the end with the same passes the every-minute job runs; this spends the business's Gemini quota.
"""
import argparse
import asyncio
import os
import re
import sys
import time
import uuid

from app.companion.kb import filetypes, ingest, ocr, pages, store


def parse_pages(spec: str | None, count: int) -> list[int]:
    """"1-5,40" -> [1, 2, 3, 4, 5, 40], kept inside 1..count. None = every page."""
    if not spec:
        return list(range(1, count + 1))
    wanted: set[int] = set()
    for part in spec.split(","):
        first, _, last = part.strip().partition("-")
        low, high = int(first), int(last or first)
        wanted.update(range(low, high + 1))
    return sorted(n for n in wanted if 1 <= n <= count)


async def _dry_page(tenant_id: str, path: str, kind: str, file_type: str, page_no: int,
                    texts: list[str]) -> tuple[str, str | None, str | None]:
    """(method, text, error) of one page, read the way the real job reads it. Writes nothing."""
    if kind == "text":
        return "text_layer", texts[page_no - 1], None
    if kind == "pdf":
        text, usable = await ingest._text_layer(path, page_no)
        if usable:
            return "text_layer", text, None
        read, error = await ocr.ocr_pdf_page(tenant_id, path, page_no)
        return "ocr", read, error
    with open(path, "rb") as handle:
        data = handle.read()
    read, error = await ocr.ocr_image(tenant_id, data, filetypes.IMAGE_MIME.get(file_type, "image/png"))
    return "ocr", read, error


async def dry_run(tenant_id: str, path: str, page_spec: str | None, show_text: bool, out=print) -> dict:
    file_type = filetypes.file_type_of(path)
    kind = filetypes.kind_of(file_type)
    texts = ingest._virtual_pages(path, file_type) if kind == "text" else []
    count = pages.count_pages(path) if kind == "pdf" else 1 if kind == "image" else len(texts)
    wanted = parse_pages(page_spec, count)
    out(f"{os.path.basename(path)}: {count} page(s), reading {len(wanted)}. Dry run: nothing is saved.")
    totals = {"text_layer": 0, "ocr": 0, "not_read": 0, "chars": 0, "seconds": 0.0}
    for page_no in wanted:
        started = time.monotonic()
        method, text, error = await _dry_page(tenant_id, path, kind, file_type, page_no, texts)
        took = time.monotonic() - started
        totals["seconds"] += took
        if error is not None:
            totals["not_read"] += 1
            out(f"page {page_no:>4}  not read ({method})  {took:6.1f}s  {error}")
            continue
        totals[method] += 1
        totals["chars"] += len(text or "")
        out(f"page {page_no:>4}  {method:<10}  {len(text or ''):>6} chars  {took:6.1f}s")
        if show_text:
            out("           " + " ".join((text or "").split())[:200])
    out(f"text layer {totals['text_layer']}, OCR {totals['ocr']}, not read {totals['not_read']}, "
        f"{totals['chars']} characters, {totals['seconds']:.1f}s")
    if totals["not_read"]:
        out("Pages that were not read need OCR. OCR uses the business's own Gemini key, which is read "
            "from the database: check the key is set and the database is reachable.")
    return totals


async def real_run(tenant_id: str, path: str, collection_name: str, tier: int, out=print) -> str:
    file_type = filetypes.file_type_of(path)
    collections = await store.list_collections(tenant_id)
    collection = next((c for c in collections if c["name"] == collection_name), None) \
        or await store.create_collection(tenant_id, collection_name)
    with open(path, "rb") as handle:
        data = handle.read()
    document_id = str(uuid.uuid4())
    remote = store.storage_path(tenant_id, document_id, file_type)
    await store.upload_file(remote, data, ingest._CONTENT_TYPES.get(file_type, "application/octet-stream"))
    title = os.path.splitext(os.path.basename(path))[0]
    await store.create_document(tenant_id, collection["id"], title=title, file_type=file_type,
                                size_bytes=len(data), tier=tier, storage_path=remote, document_id=document_id)
    out(f"Registered \"{title}\" as {document_id} in \"{collection_name}\" (tier {tier}).")
    started, status = time.monotonic(), "processing"
    while status == "processing":
        status = await ingest.run_document(tenant_id, document_id)
        ledger = await store.list_pages(tenant_id, document_id)
        done = sum(1 for p in ledger if p["status"] != "pending")
        out(f"  {time.monotonic() - started:6.0f}s  {done} of {len(ledger)} pages  status {status}")
    for page in await store.list_pages(tenant_id, document_id):
        note = f"  {page['error']}" if page["status"] == "failed" else ""
        out(f"page {page['page_no']:>4}  {page['status']:<7} {page.get('method') or '-':<10} "
            f"{page.get('char_count') or 0:>6} chars  tries {page.get('attempts') or 0}{note}")
    document = await store.get_document(tenant_id, document_id) or {}
    passages = await store.list_chunks(tenant_id, document_id)
    out(f"{status}: {len(passages)} passages, {time.monotonic() - started:.0f}s. {document.get('error') or ''}".rstrip())
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.companion.kb.ingest_cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tenant_id")
    parser.add_argument("path")
    parser.add_argument("--collection", help="collection name (made if missing); needed without --dry-run")
    parser.add_argument("--tier", type=int, choices=(1, 2), default=2, help="1 = main resource, 2 = book")
    parser.add_argument("--pages", help='with --dry-run: "3", "1-5" or "1-5,40"')
    parser.add_argument("--dry-run", action="store_true", help="read and print, save nothing")
    parser.add_argument("--show-text", action="store_true", help="with --dry-run: print the start of each page")
    args = parser.parse_args(argv)
    if args.pages and not re.fullmatch(r"\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*", args.pages):
        print('--pages must look like "3", "1-5" or "1-5,40".')
        return 2
    if not os.path.isfile(args.path):
        print(f"File not found: {args.path}")
        return 2
    try:
        if args.dry_run:
            asyncio.run(dry_run(args.tenant_id, args.path, args.pages, args.show_text))
            return 0
        if args.pages or args.show_text:
            print("--pages and --show-text only work with --dry-run.")
            return 2
        if not args.collection:
            print("--collection NAME is needed to save a book (or add --dry-run).")
            return 2
        return 0 if asyncio.run(real_run(args.tenant_id, args.path, args.collection, args.tier)) != "failed" else 1
    except filetypes.UnsupportedFileType as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
