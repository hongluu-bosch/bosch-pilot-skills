param(
    [string]$ReportDir = "review-reports",
    [string]$ReportBase = "static-code-review-report.current-file"
)

$ErrorActionPreference = "Stop"

$bundleRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $bundleRoot

function Resolve-ProjectPath {
    param([string]$PathValue)

    if (-not $PathValue) {
        return ""
    }

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }

    return (Join-Path $projectRoot $PathValue)
}

$resolvedReportDir = Resolve-ProjectPath $ReportDir
$reportRoot = [System.IO.Path]::GetFullPath($resolvedReportDir)

$reportFiles = @(Get-ChildItem -Path $reportRoot -File -Filter "static-code-review-report*" | Where-Object {
    $_.Extension -in @('.md', '.html') -or $_.Name.EndsWith('.zh-CN.html')
} | Select-Object -ExpandProperty FullName)

$existingFiles = @($reportFiles | Where-Object { -not ($_ -like "*\archive\*") })

if ($existingFiles.Count -eq 0) {
    [pscustomobject]@{
        status = "no_reports"
        reportDir = $reportRoot
    } | ConvertTo-Json -Depth 5
    exit 0
}

$archiveRoot = Join-Path $reportRoot "archive"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fffffff"
New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null

function Get-ArchivedFileName {
    param(
        [string]$FileName,
        [string]$ArchiveStamp
    )

    if ($FileName.EndsWith('.zh-CN.html')) {
        $baseName = $FileName.Substring(0, $FileName.Length - '.zh-CN.html'.Length)
        return "$baseName.$ArchiveStamp.zh-CN.html"
    }

    $nameWithoutExtension = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    $extension = [System.IO.Path]::GetExtension($FileName)
    return "$nameWithoutExtension.$ArchiveStamp$extension"
}

$movedFiles = @()
foreach ($filePath in $existingFiles) {
    $archivedFileName = Get-ArchivedFileName -FileName ([System.IO.Path]::GetFileName($filePath)) -ArchiveStamp $timestamp
    $destinationPath = Join-Path $archiveRoot $archivedFileName
    Move-Item -Force -LiteralPath $filePath -Destination $destinationPath
    $movedFiles += $destinationPath
}

[pscustomobject]@{
    status = "archived"
    archiveDir = $archiveRoot
    movedFiles = $movedFiles
} | ConvertTo-Json -Depth 5