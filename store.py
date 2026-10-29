import json
import secrets
from datetime import datetime, timezone

import pymysql
from pymysql.cursors import DictCursor

from config import KSA, TARGET_JID, WA

CREATE_JOBS = """
CREATE TABLE IF NOT EXISTS whatsapp_jobs (
  id bigint NOT NULL AUTO_INCREMENT,
  created_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  public_id char(32) NOT NULL,
  whatsapp_message_id varchar(255) NOT NULL,
  message_db_id varchar(191) NOT NULL,
  chat_jid varchar(255) NOT NULL,
  sender_jid varchar(255) DEFAULT NULL,
  participant_jid varchar(255) DEFAULT NULL,
  message_type varchar(32) NOT NULL DEFAULT 'TEXT',
  message_timestamp datetime(6) NOT NULL,
  title varchar(512) NOT NULL DEFAULT '',
  location varchar(512) NOT NULL DEFAULT '',
  company varchar(255) NOT NULL DEFAULT '',
  contact_phone varchar(64) NOT NULL DEFAULT '',
  contact_email varchar(254) NOT NULL DEFAULT '',
  positions varchar(64) NOT NULL DEFAULT '',
  duration varchar(128) NOT NULL DEFAULT '',
  salary varchar(128) NOT NULL DEFAULT '',
  requirements text,
  responsibilities text,
  raw_text longtext NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'new',
  is_job tinyint(1) NOT NULL DEFAULT 1,
  source varchar(64) NOT NULL DEFAULT 'whatsapp',
  PRIMARY KEY (id),
  UNIQUE KEY uq_whatsapp_jobs_message (whatsapp_message_id),
  UNIQUE KEY uq_whatsapp_jobs_public_id (public_id),
  KEY idx_whatsapp_jobs_chat_jid (chat_jid),
  KEY idx_whatsapp_jobs_status (status),
  KEY idx_whatsapp_jobs_message_ts (message_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""

CREATE_STATE = """
CREATE TABLE IF NOT EXISTS whatsapp_job_sync_state (
  id tinyint NOT NULL DEFAULT 1,
  target_chat_jid varchar(255) NOT NULL,
  last_message_timestamp datetime(6) DEFAULT NULL,
  last_message_db_id varchar(191) DEFAULT NULL,
  last_run_at datetime(6) DEFAULT NULL,
  last_run_status varchar(32) NOT NULL DEFAULT 'idle',
  last_error text,
  total_imported bigint NOT NULL DEFAULT 0,
  updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""


def connect(cfg: dict):
    return pymysql.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=20,
        autocommit=False,
    )


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_JOBS)
        cur.execute(CREATE_STATE)
        cur.execute(
            """
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'whatsapp_jobs'
            """
        )
        columns = {row["COLUMN_NAME"] for row in cur.fetchall()}
        if "salary" not in columns:
            cur.execute(
                "ALTER TABLE whatsapp_jobs ADD COLUMN salary varchar(128) NOT NULL DEFAULT '' AFTER duration"
            )
        if "responsibilities" not in columns:
            cur.execute(
                "ALTER TABLE whatsapp_jobs ADD COLUMN responsibilities text NULL AFTER requirements"
            )
        cur.execute(
            """
            INSERT INTO whatsapp_job_sync_state (id, target_chat_jid)
            VALUES (1, %s)
            ON DUPLICATE KEY UPDATE target_chat_jid = VALUES(target_chat_jid)
            """,
            (TARGET_JID,),
        )
    conn.commit()


def load_state(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM whatsapp_job_sync_state WHERE id = 1")
        row = cur.fetchone()
    return row or {}


def save_state(conn, *, status: str, cursor_ts, cursor_id, imported_delta: int, error: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE whatsapp_job_sync_state
            SET last_message_timestamp = COALESCE(%s, last_message_timestamp),
                last_message_db_id = COALESCE(%s, last_message_db_id),
                last_run_at = CURRENT_TIMESTAMP(6),
                last_run_status = %s,
                last_error = %s,
                total_imported = total_imported + %s
            WHERE id = 1
            """,
            (cursor_ts, cursor_id, status, error, imported_delta),
        )
    conn.commit()


def _wa_url(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "966" + digits[1:]
    if len(digits) < 10:
        return ""
    return f"https://wa.me/{digits}"[:1000]


def _days_ago(posted_at: datetime) -> int:
    if posted_at is None:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, (now - posted_at).days)


def upsert_job(conn, message: dict, job: dict) -> str:
    message_key = message.get("whatsappMessageId") or message["id"]
    source_id = f"whatsapp-{message_key}"[:255]
    posted_at = message["messageTimestamp"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    raw_description = json.dumps(
        {
            "site": "whatsapp",
            "chat_jid": message.get("chatJid") or TARGET_JID,
            "message_id": message_key,
            "message_db_id": message["id"],
            "sender_jid": message.get("senderJid"),
            "contact_phone": job.get("contact_phone") or "",
            "contact_email": job.get("contact_email") or "",
            "positions": job.get("positions") or "",
            "duration": job.get("duration") or "",
            "salary": job.get("salary") or "",
            "is_remote": job.get("work_model") == "remote",
            "date_posted": posted_at.strftime("%Y-%m-%d") if posted_at else "",
        },
        ensure_ascii=False,
    )
    title = (job.get("title") or "WhatsApp job")[:512]
    values = {
        "title": title,
        "location": (job.get("location") or "Saudi Arabia")[:512],
        "description": job.get("raw_text") or title,
        "posted_at": posted_at,
        "is_active": 1,
        "company": job.get("company") or None,
        "source_id": source_id,
        "skills": json.dumps(job.get("skills") or [], ensure_ascii=False),
        "state": (job.get("state") or "Saudi Arabia")[:255],
        "platform": "whatsapp",
        "days_ago": _days_ago(posted_at),
        "url": _wa_url(job.get("contact_phone") or ""),
        "raw_description": raw_description,
        "title_ar": (job.get("title_ar") or "")[:512],
        "description_ar": job.get("description_ar") or "",
        "job_type": job.get("job_type") or "fulltime",
        "work_model": job.get("work_model") or "unknown",
        "experience_level": job.get("experience_level") or "unknown",
        "years_experience": job.get("years_experience"),
        "visa_sponsorship": job.get("visa_sponsorship") or "unknown",
        "clearance_required": job.get("clearance_required") or "unknown",
        "saudi_national_required": job.get("saudi_national_required") or "no",
        "sponsors_work_visa": int(job.get("sponsors_work_visa") or 0),
        "saudi_national_preferred": int(job.get("saudi_national_preferred") or 0),
        "listing_inferred": 1,
        "platform_posted_at": posted_at,
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "currency": (job.get("currency") or "")[:3],
        "compensation_period": (job.get("compensation_period") or "")[:20],
        "updated_at": now,
        "last_seen_at": now,
    }
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE source_id = %s", (source_id,))
        existing = cur.fetchone()
        if existing:
            assignments = ", ".join(f"{column} = %s" for column in values)
            cur.execute(
                f"UPDATE jobs SET {assignments} WHERE source_id = %s",
                tuple(values.values()) + (source_id,),
            )
            return "updated"
        cur.execute(
            """
            INSERT INTO jobs (
              created_at, updated_at, public_id, title, location, description,
              posted_at, is_active, company, source_id, skills, state, platform,
              days_ago, url, first_seen_at, last_seen_at, raw_description,
              title_ar, description_ar, job_type, work_model, experience_level,
              years_experience, visa_sponsorship, clearance_required,
              saudi_national_required, sponsors_work_visa, saudi_national_preferred,
              listing_inferred, platform_posted_at, salary_min, salary_max,
              currency, compensation_period
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                now,
                values["updated_at"],
                secrets.token_hex(16),
                values["title"],
                values["location"],
                values["description"],
                values["posted_at"],
                values["is_active"],
                values["company"],
                values["source_id"],
                values["skills"],
                values["state"],
                values["platform"],
                values["days_ago"],
                values["url"],
                now,
                values["last_seen_at"],
                values["raw_description"],
                values["title_ar"],
                values["description_ar"],
                values["job_type"],
                values["work_model"],
                values["experience_level"],
                values["years_experience"],
                values["visa_sponsorship"],
                values["clearance_required"],
                values["saudi_national_required"],
                values["sponsors_work_visa"],
                values["saudi_national_preferred"],
                values["listing_inferred"],
                values["platform_posted_at"],
                values["salary_min"],
                values["salary_max"],
                values["currency"],
                values["compensation_period"],
            ),
        )
    return "inserted"


def fetch_messages(conn, *, after_ts: datetime | None, after_id: str | None, limit: int) -> list[dict]:
    sql = """
        SELECT id, whatsappMessageId, chatJid, senderJid, participantJid,
               type, text, caption, messageTimestamp
        FROM message
        WHERE (chatJid = %s OR chatAlternateJid = %s)
          AND type IN ('TEXT', 'IMAGE', 'DOCUMENT', 'VIDEO')
          AND COALESCE(text, caption, '') <> ''
    """
    params: list = [TARGET_JID, TARGET_JID]
    if after_ts is not None:
        sql += " AND (messageTimestamp > %s OR (messageTimestamp = %s AND id > %s))"
        params.extend([after_ts, after_ts, after_id or ""])
    sql += " ORDER BY messageTimestamp ASC, id ASC LIMIT %s"
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def list_jobs(conn, limit: int = 20) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source_id, title, company, state, location, platform,
                   job_type, work_model, experience_level, years_experience,
                   posted_at, url
            FROM jobs
            WHERE platform = 'whatsapp'
            ORDER BY posted_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())
