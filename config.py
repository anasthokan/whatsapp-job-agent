import os
from pathlib import Path


def load_env(path: Path | None = None) -> None:
    env_path = path or Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def setting(name: str, default: str = "") -> str:
    load_env()
    return os.environ.get(name, default).strip()


WA = {
    "host": setting("WA_HOST"),
    "user": setting("WA_USER"),
    "password": setting("WA_PASSWORD"),
    "database": setting("WA_DATABASE", "whatsapp_db"),
}

KSA = {
    "host": setting("KSA_HOST"),
    "user": setting("KSA_USER"),
    "password": setting("KSA_PASSWORD"),
    "database": setting("KSA_DATABASE", "ksajob"),
}

TARGET_JID = setting("TARGET_JID", "966563226748-1448363692@g.us")
POLL_SECONDS = int(setting("POLL_SECONDS", "3600") or "3600")
BATCH_SIZE = int(setting("BATCH_SIZE", "200") or "200")
