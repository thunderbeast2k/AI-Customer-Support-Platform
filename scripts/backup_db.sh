#!/usr/bin/env bash
# ==============================================================================
# Database Automated Backup Script (Phase 10 Production Ops)
# Dumps PostgreSQL database, creates gzipped snapshot, and generates SHA256 checksum.
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_NAME="${POSTGRES_DB:-customer_support_db}"
DB_USER="${POSTGRES_USER:-postgres}"
CONTAINER_NAME="${DB_CONTAINER:-customer_support_db}"
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"

mkdir -p "${BACKUP_DIR}"

echo "[INFO] Starting database backup for '${DB_NAME}' at $(date -u +"%Y-%m-%dT%H:%M:%SZ")..."

# Execute pg_dump inside container with gzip stream
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists | gzip -9 > "${BACKUP_FILE}"
else
    # Fallback to local pg_dump
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists | gzip -9 > "${BACKUP_FILE}"
fi

# Generate SHA256 integrity checksum
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
fi

FILE_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[SUCCESS] Backup completed successfully!"
echo "          Destination: ${BACKUP_FILE} (${FILE_SIZE})"
echo "          Checksum:    ${CHECKSUM_FILE}"

# Optional 30-day retention pruning
find "${BACKUP_DIR}" -name "${DB_NAME}_*.sql.gz" -type f -mtime +30 -delete 2>/dev/null || true
echo "[INFO] Pruned backups older than 30 days."
