# =============================================================================
# export-for-claude.ps1
# =============================================================================
# Zips the project's source files for upload to Claude.
#
# Selection is DENY-LIST based: a file is included unless it lives in an
# excluded directory, matches an excluded name pattern, carries a binary/blob
# extension, or exceeds the size threshold. New file types therefore land in
# the snapshot automatically without touching this script.
#
# Every exclusion is logged to EXCLUDED-FILES.txt at the zip root, so a missing
# file can be traced to the rule that dropped it.
#
# The project root is derived from this script's own location (parent of
# .claude\), so it works from the main checkout and from any `git worktree`.
#
# Usage (from anywhere):
#   .\.claude\export-for-claude.ps1
#   .\.claude\export-for-claude.ps1 -MaxFileSizeMB 5
#   .\.claude\export-for-claude.ps1 -MaxFileSizeMB 0          # no size limit
#   .\.claude\export-for-claude.ps1 -ListSkipped               # full console report
#   .\.claude\export-for-claude.ps1 -OutputPath "C:\temp\p.zip"
#
# Output: project-snapshot.zip in the project root (or custom path)
# =============================================================================

param(
    [string]$OutputPath = "",
    [double]$MaxFileSizeMB = 2,
    [switch]$ListSkipped
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TempDir = Join-Path $ProjectRoot ".claude\export-temp"
$ManifestName = "EXCLUDED-FILES.txt"

if ($OutputPath -eq "") {
    $OutputPath = Join-Path $ProjectRoot "project-snapshot.zip"
}

$SizeLimit = if ($MaxFileSizeMB -gt 0) { $MaxFileSizeMB * 1MB } else { [double]::MaxValue }

# =============================================================================
# Deny list: directory names, pruned at any depth
# =============================================================================
$ExcludeDirNames = @(
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".ipynb_checkpoints",
    ".idea",
    "dist",
    "build",
    "*.egg-info",
    "graph-cache",
    "htmlcov",
    "credentials",
    "export-temp"
)

# =============================================================================
# Deny list: paths relative to the project root (prefix match)
# =============================================================================
$ExcludeRelativePaths = @(
    "backend\models\route\routing\docker\data",
    "backend\db\dev\data"
)

# =============================================================================
# Deny list: file name patterns (secrets, lockfiles, generated noise)
# =============================================================================
$ExcludeFilePatterns = @(
    "*.env",
    ".env",
    ".env.*",
    "*.env.bak*",
    "uv.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "*.log",
    "project-snapshot.zip"
)

# Overrides that win over every deny rule above
$AlwaysIncludePatterns = @(
    "*.env.example",
    "*.env.sample",
    "*.env.template"
)

# =============================================================================
# Deny list: binary / blob extensions (unreadable in a snapshot)
# =============================================================================
$ExcludeExtensions = @(
    ".pbf", ".osm", ".jar", ".class",
    ".zip", ".7z", ".gz", ".tgz", ".tar", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".whl", ".pyc", ".pyo", ".pdb",
    ".db", ".sqlite", ".sqlite3", ".dump", ".bak",
    ".parquet", ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5", ".feather",
    ".shp", ".shx", ".dbf", ".prj", ".sbn", ".sbx", ".cpg", ".gpkg", ".mbtiles",
    ".tif", ".tiff", ".pdf", ".psd",
    ".mp4", ".mov", ".avi", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".xlsx", ".xls", ".docx", ".doc", ".pptx"
)

$prunedDirs = [System.Collections.Generic.List[string]]::new()
$excluded = [System.Collections.Generic.List[object]]::new()

function Test-PatternMatch {
    param([string]$Value, [string[]]$Patterns)

    foreach ($pattern in $Patterns) {
        if ($Value -like $pattern) { return $true }
    }
    return $false
}

function Add-Exclusion {
    param([string]$Path, [string]$Reason, [double]$MB = 0)

    $excluded.Add([pscustomobject]@{ Path = $Path; Reason = $Reason; MB = $MB })
}

# Walks the tree depth-first, pruning excluded directories so we never
# enumerate .venv / node_modules / .git at all. Pruned directories are
# recorded as a single entry each instead of file by file.
function Get-CandidateFiles {
    param([string]$Path)

    foreach ($item in Get-ChildItem -LiteralPath $Path -Force) {
        if ($item.PSIsContainer) {
            if (Test-PatternMatch $item.Name $ExcludeDirNames) {
                $prunedDirs.Add($item.FullName.Substring($ProjectRoot.Length + 1))
            }
            else {
                Get-CandidateFiles -Path $item.FullName
            }
        }
        else {
            $item
        }
    }
}

Write-Host "Project root: $ProjectRoot" -ForegroundColor DarkGray
Write-Host "Collecting files (deny-list, size limit $MaxFileSizeMB MB)..." -ForegroundColor Cyan

if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
}
if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $TempDir | Out-Null

$collected = 0

foreach ($file in Get-CandidateFiles -Path $ProjectRoot) {
    $relativePath = $file.FullName.Substring($ProjectRoot.Length + 1)

    if (-not (Test-PatternMatch $file.Name $AlwaysIncludePatterns)) {
        $excludedByPath = $null
        foreach ($candidate in $ExcludeRelativePaths) {
            if ($relativePath -eq $candidate -or $relativePath -like "$candidate\*") {
                $excludedByPath = $candidate
                break
            }
        }
        if ($excludedByPath) {
            Add-Exclusion $relativePath "path: $excludedByPath"
            continue
        }

        if (Test-PatternMatch $file.Name $ExcludeFilePatterns) {
            Add-Exclusion $relativePath "name pattern"
            continue
        }

        if ($ExcludeExtensions -contains $file.Extension.ToLower()) {
            Add-Exclusion $relativePath "extension: $($file.Extension.ToLower())"
            continue
        }

        if ($file.Length -gt $SizeLimit) {
            $fileMB = [math]::Round($file.Length / 1MB, 2)
            Add-Exclusion $relativePath "size" $fileMB
            continue
        }
    }

    $destPath = Join-Path $TempDir $relativePath
    $destDir = Split-Path $destPath -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    Copy-Item -LiteralPath $file.FullName -Destination $destPath
    $collected++
}

# =============================================================================
# Exclusion manifest, written to the zip root
# =============================================================================
$bySize = @($excluded | Where-Object { $_.Reason -eq "size" } | Sort-Object MB -Descending)
$byRule = @($excluded | Where-Object { $_.Reason -ne "size" } | Sort-Object Path)
$limitLabel = if ($MaxFileSizeMB -gt 0) { "$MaxFileSizeMB MB" } else { "none" }

$manifest = [System.Collections.Generic.List[string]]::new()
$manifest.Add("Exclusions for $(Split-Path $OutputPath -Leaf)")
$manifest.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$manifest.Add("Project root: $ProjectRoot")
$manifest.Add("Size limit: $limitLabel")
$manifest.Add("Included: $collected files")
$manifest.Add("")
$manifest.Add("Selection is deny-list based: everything is exported unless a rule below")
$manifest.Add("dropped it. Adjust the deny lists in .claude\export-for-claude.ps1.")
$manifest.Add("")

$manifest.Add("--- PRUNED DIRECTORIES ($($prunedDirs.Count)) ---")
$manifest.Add("Not walked at all, so their contents are not listed individually.")
if ($prunedDirs.Count -eq 0) {
    $manifest.Add("(none)")
}
else {
    foreach ($dir in ($prunedDirs | Sort-Object)) {
        $manifest.Add($dir)
    }
}
$manifest.Add("")

$manifest.Add("--- EXCLUDED BY SIZE ($($bySize.Count)) ---")
if ($bySize.Count -eq 0) {
    $manifest.Add("(none)")
}
else {
    foreach ($entry in $bySize) {
        $manifest.Add(("{0,8} MB  {1}" -f $entry.MB, $entry.Path))
    }
}
$manifest.Add("")

$manifest.Add("--- EXCLUDED BY RULE ($($byRule.Count)) ---")
if ($byRule.Count -eq 0) {
    $manifest.Add("(none)")
}
else {
    foreach ($entry in $byRule) {
        $manifest.Add(("{0}  [{1}]" -f $entry.Path, $entry.Reason))
    }
}

Set-Content -LiteralPath (Join-Path $TempDir $ManifestName) -Value $manifest -Encoding UTF8

Write-Host "Collected $collected files." -ForegroundColor Green
Write-Host "Excluded: $($byRule.Count) by rule, $($bySize.Count) by size, $($prunedDirs.Count) directories pruned." -ForegroundColor DarkGray

if ($bySize.Count -gt 0) {
    $shown = if ($ListSkipped) { $bySize } else { $bySize | Select-Object -First 10 }
    Write-Host "Over the $MaxFileSizeMB MB limit:" -ForegroundColor Yellow
    foreach ($entry in $shown) {
        Write-Host ("  {0,8} MB  {1}" -f $entry.MB, $entry.Path) -ForegroundColor Yellow
    }
    if (-not $ListSkipped -and $bySize.Count -gt 10) {
        Write-Host "  ... $($bySize.Count - 10) more, see $ManifestName in the zip" -ForegroundColor DarkGray
    }
}

Write-Host "Creating zip at $OutputPath..." -ForegroundColor Cyan
Compress-Archive -Path "$TempDir\*" -DestinationPath $OutputPath -Force
Remove-Item $TempDir -Recurse -Force

$zipBytes = (Get-Item $OutputPath).Length
$zipSizeMB = [math]::Round($zipBytes / 1MB, 2)
Write-Host "Done. $OutputPath ($zipSizeMB MB), exclusions listed in $ManifestName" -ForegroundColor Green