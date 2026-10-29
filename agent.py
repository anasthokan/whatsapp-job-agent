"""Pick job posts from a WhatsApp group table and store them in ksajob."""

import argparse
import time
import traceback

from config import BATCH_SIZE, POLL_SECONDS, TARGET_JID
from parser import parse_job
from store import (
    connect,
    ensure_schema,
    fetch_messages,
    list_jobs,
    load_state,
    save_state,
    upsert_job,
    KSA,
    WA,
)


def message_body(row: dict) -> str:
    return (row.get("text") or row.get("caption") or "").strip()


def sync_once(full: bool = False) -> dict:
    wa = connect(WA)
    ksa = connect(KSA)
    scanned = 0
    inserted = 0
    updated = 0
    skipped = 0
    cursor_ts = None
    cursor_id = None
    try:
        ensure_schema(ksa)
        state = load_state(ksa)
        after_ts = None if full else state.get("last_message_timestamp")
        after_id = None if full else state.get("last_message_db_id")
        while True:
            rows = fetch_messages(wa, after_ts=after_ts, after_id=after_id, limit=BATCH_SIZE)
            if not rows:
                break
            for row in rows:
                scanned += 1
                cursor_ts = row["messageTimestamp"]
                cursor_id = row["id"]
                job = parse_job(message_body(row))
                if not job:
                    skipped += 1
                    continue
                action = upsert_job(ksa, row, job)
                if action == "inserted":
                    inserted += 1
                else:
                    updated += 1
            ksa.commit()
            after_ts = cursor_ts
            after_id = cursor_id
            if len(rows) < BATCH_SIZE:
                break
        save_state(
            ksa,
            status="ok",
            cursor_ts=cursor_ts,
            cursor_id=cursor_id,
            imported_delta=inserted,
            error=None,
        )
        return {
            "group": TARGET_JID,
            "scanned": scanned,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
        }
    except Exception as exc:
        ksa.rollback()
        try:
            save_state(
                ksa,
                status="error",
                cursor_ts=None,
                cursor_id=None,
                imported_delta=0,
                error=str(exc)[:2000],
            )
        except Exception:
            traceback.print_exc()
        raise
    finally:
        wa.close()
        ksa.close()


def print_status() -> None:
    ksa = connect(KSA)
    try:
        ensure_schema(ksa)
        state = load_state(ksa)
        print(f"group: {state.get('target_chat_jid')}")
        print(f"last_run: {state.get('last_run_at')} ({state.get('last_run_status')})")
        print(f"cursor: {state.get('last_message_timestamp')} / {state.get('last_message_db_id')}")
        print(f"total_imported: {state.get('total_imported')}")
        if state.get("last_error"):
            print(f"last_error: {state.get('last_error')}")
        print("--- latest whatsapp jobs ---")
        for job in list_jobs(ksa):
            bits = [f"#{job['id']}", job["source_id"], job["title"] or "(no title)"]
            if job["location"]:
                bits.append(job["location"])
            if job["experience_level"] and job["experience_level"] != "unknown":
                bits.append(job["experience_level"])
            print(" | ".join(bits))
    finally:
        ksa.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gather WhatsApp group jobs into ksajob.jobs")
    parser.add_argument("command", choices=("sync", "watch", "status"))
    parser.add_argument("--full", action="store_true", help="Re-read the whole group, not only new messages")
    args = parser.parse_args()
    if args.command == "status":
        print_status()
        return
    if args.command == "sync":
        result = sync_once(full=args.full)
        print(
            f"scanned={result['scanned']} inserted={result['inserted']} "
            f"updated={result['updated']} skipped={result['skipped']}"
        )
        return
    print(f"watching {TARGET_JID} every {POLL_SECONDS}s")
    while True:
        try:
            result = sync_once(full=False)
            print(
                f"scanned={result['scanned']} inserted={result['inserted']} "
                f"updated={result['updated']} skipped={result['skipped']}"
            )
        except Exception as exc:
            print(f"sync failed: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
