# =============================================================================
# export-for-claude.ps1
# =============================================================================
# Zips all relevant source files from the night-train-target-network project
# for upload to Claude. Run from anywhere — uses hardcoded project root.
#
# Usage (from repo root or anywhere):
#   .\.claude\export-for-claude.ps1
#   .\.claude\export-for-claude.ps1 -OutputPath "C:\temp\project.zip"
#
# Output: project-snapshot.zip in the project root (or custom path)
# =============================================================================

param(
    [string]$OutputPath = ""
)

$ProjectRoot = "C:\Users\david\PycharmProjects\night-train-target-network"
$TempDir = Join-Path $ProjectRoot ".claude\export-temp"

if ($OutputPath -eq "") {
    $OutputPath = Join-Path $ProjectRoot "project-snapshot.zip"
}

# Remove existing zip if present
if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
}

# Create temp staging directory (clean slate)
if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $TempDir | Out-Null

# =============================================================================
# File patterns to include
# =============================================================================
$IncludeExtensions = @(
    "*.py",
    "*.yml",
    "*.yaml",
    "*.toml",
    "*.sql",
    "*.sh",
    "*.json",
    "*.md",
    "*.txt",
    "*.env.example",
    "Dockerfile",
    ".dockerignore",
    ".gitattributes",
    "*.cfg",
    "*.ini",
    "*.ts",
    "*.tsx",
    "*.vue",
    "*.css",
    "*.html"
)

# =============================================================================
# Directories to exclude entirely
# =============================================================================
$ExcludeDirs = @(
    ".venv",
    "__pycache__",
    ".git",
    ".idea",
    "node_modules",
    "graph-cache",
    ".pytest_cache",
    ".ruff_cache",
    "export-temp",
    "dist",
    "build",
    "*.egg-info"
)

# =============================================================================
# Specific files/paths to exclude (large or sensitive)
# =============================================================================
$ExcludePatterns = @(
    "credentials\*",
    "*.pbf",
    "*.jar",
    "*.zip",
    "*.7z",
    "uv.lock",
    "project-snapshot.zip"
)

Write-Host "Collecting files from $ProjectRoot..." -ForegroundColor Cyan

$collected = 0

Get-ChildItem -Path $ProjectRoot -Recurse -File | Where-Object {
    $file = $_
    $relativePath = $file.FullName.Substring($ProjectRoot.Length + 1)

    # Exclude by directory name
    $inExcludedDir = $false
    foreach ($excDir in $ExcludeDirs) {
        if ($relativePath -like "*\$excDir\*" -or $relativePath -like "*\$excDir") {
            $inExcludedDir = $true
            break
        }
    }
    if ($inExcludedDir) { return $false }

    # Exclude by specific pattern
    $isExcluded = $false
    foreach ($pattern in $ExcludePatterns) {
        if ($relativePath -like $pattern) {
            $isExcluded = $true
            break
        }
    }
    if ($isExcluded) { return $false }

    # Include by extension or exact filename
    $included = $false
    foreach ($ext in $IncludeExtensions) {
        if ($file.Name -like $ext) {
            $included = $true
            break
        }
    }
    return $included

} | ForEach-Object {
    $file = $_
    $relativePath = $file.FullName.Substring($ProjectRoot.Length + 1)
    $destPath = Join-Path $TempDir $relativePath
    $destDir = Split-Path $destPath -Parent

    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    Copy-Item $file.FullName -Destination $destPath
    $collected++
}

Write-Host "Collected $collected files." -ForegroundColor Green
Write-Host "Creating zip at $OutputPath..." -ForegroundColor Cyan

Compress-Archive -Path "$TempDir\*" -DestinationPath $OutputPath -Force

# Cleanup temp dir
Remove-Item $TempDir -Recurse -Force

$zipSize = (Get-Item $OutputPath).Length / 1KB
Write-Host "Done. $OutputPath ($([math]::Round($zipSize)) KB)" -ForegroundColor Green