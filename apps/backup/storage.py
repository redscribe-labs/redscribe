import os
from pathlib import Path


def write_encrypted_backup_file(encrypted: bytes, backup_dir: Path, filename: str) -> Path:
    is_new = not backup_dir.exists()
    backup_dir.mkdir(parents=True, exist_ok=True)
    if is_new:
        os.chmod(backup_dir, 0o700)
    path = backup_dir / filename
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(encrypted)
    return path
