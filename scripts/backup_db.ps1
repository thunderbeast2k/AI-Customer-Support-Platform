# ==============================================================================
# Database Automated Backup Script for Windows PowerShell (Phase 10)
# ==============================================================================
param(
    [string]$DbName = "customer_support_db",
    [string]$DbUser = "postgres",
    [string]$ContainerName = "customer_support_db",
    [string]$BackupDir = "./backups"
)

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFile = "$BackupDir/${DbName}_${Timestamp}.sql"

if (!(Test-Path -Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

Write-Host "[INFO] Starting database backup for $DbName to $BackupFile..." -ForegroundColor Cyan

docker exec -i $ContainerName pg_dump -U $DbUser -d $DbName --clean --if-exists > $BackupFile

if (Test-Path -Path $BackupFile) {
    $Hash = Get-FileHash -Path $BackupFile -Algorithm SHA256
    $Hash.Hash | Out-File -FilePath "$BackupFile.sha256"
    Write-Host "[SUCCESS] Database backup completed: $BackupFile" -ForegroundColor Green
    Write-Host "          SHA256: $($Hash.Hash)" -ForegroundColor Gray
} else {
    Write-Error "[ERROR] Backup failed to generate."
}
