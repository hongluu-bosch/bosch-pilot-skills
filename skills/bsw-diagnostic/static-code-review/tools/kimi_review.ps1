param(
    [ValidateSet("Prepare", "PrepareClipboard", "Run", "RunWeb", "Import", "ImportClipboard", "Validate", "Gate", "InstallCline")]
    [string]$Action = "Validate",
    [string]$Source = "",
    [ValidateSet("file", "function", "selection")]
    [string]$ScopeKind = "file",
    [string]$ScopeName = "",
    [string]$ReviewInput = "",
    [string]$Response = "",
    [string]$ReportDir = "review-reports",
    [string]$ReportBase = "static-code-review-report.current-file",
    [string]$Output = "",
    [string]$ResponseOutput = "",
    [string]$SkillPackOutput = ""
)

$ErrorActionPreference = "Stop"

$bundleRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $bundleRoot
$pipelinePath = Join-Path $PSScriptRoot "kimi_review_pipeline.py"
$installClinePath = Join-Path $PSScriptRoot "install_cline_integration.ps1"

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

$resolvedSource = Resolve-ProjectPath $Source
$resolvedReviewInput = Resolve-ProjectPath $ReviewInput
$resolvedResponse = Resolve-ProjectPath $Response
$resolvedReportDir = Resolve-ProjectPath $ReportDir
$resolvedOutput = Resolve-ProjectPath $Output
$resolvedResponseOutput = Resolve-ProjectPath $ResponseOutput
$resolvedSkillPackOutput = Resolve-ProjectPath $SkillPackOutput

if ($Action -eq "InstallCline") {
    powershell -ExecutionPolicy Bypass -File $installClinePath
    exit $LASTEXITCODE
}

$arguments = @($pipelinePath)

switch ($Action) {
    "Prepare" {
        if (-not $resolvedSource) {
            throw "-Source is required for Action Prepare."
        }
        $arguments += @("prepare", "--source", $resolvedSource)
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
        if ($resolvedReviewInput) {
            $arguments += @("--review-input", $resolvedReviewInput)
        }
        if ($resolvedOutput) {
            $arguments += @("--output", $resolvedOutput)
        }
    }
    "PrepareClipboard" {
        if (-not $resolvedSource) {
            throw "-Source is required for Action PrepareClipboard."
        }
        $arguments += @("prepare-clipboard", "--source", $resolvedSource)
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
        if ($resolvedReviewInput) {
            $arguments += @("--review-input", $resolvedReviewInput)
        }
        if ($resolvedOutput) {
            $arguments += @("--output", $resolvedOutput)
        }
    }
    "Run" {
        if (-not $resolvedSource) {
            throw "-Source is required for Action Run."
        }
        $arguments += @("run", "--source", $resolvedSource, "--report-dir", $resolvedReportDir, "--report-base", $ReportBase)
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
        if ($resolvedReviewInput) {
            $arguments += @("--review-input", $resolvedReviewInput)
        }
        if ($resolvedResponseOutput) {
            $arguments += @("--response-output", $resolvedResponseOutput)
        }
    }
    "RunWeb" {
        if (-not $resolvedSource) {
            throw "-Source is required for Action RunWeb."
        }
        $automationRoot = Join-Path $bundleRoot "automation"
        $playwrightPath = Join-Path $automationRoot "node_modules\playwright"
        if (-not (Test-Path $playwrightPath)) {
            Push-Location $automationRoot
            try {
                npm install
                if ($LASTEXITCODE -ne 0) {
                    exit $LASTEXITCODE
                }
            }
            finally {
                Pop-Location
            }
        }
        $arguments += @("run-web", "--source", $resolvedSource, "--report-dir", $resolvedReportDir, "--report-base", $ReportBase)
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
        if ($resolvedReviewInput) {
            $arguments += @("--review-input", $resolvedReviewInput)
        }
        if ($resolvedResponseOutput) {
            $arguments += @("--response-output", $resolvedResponseOutput)
        }
        if ($resolvedSkillPackOutput) {
            $arguments += @("--skill-pack-output", $resolvedSkillPackOutput)
        }
    }
    "Import" {
        if (-not $resolvedResponse) {
            throw "-Response is required for Action Import."
        }
        $arguments += @("import", "--response", $resolvedResponse, "--report-dir", $resolvedReportDir, "--report-base", $ReportBase)
        if ($resolvedSource) {
            $arguments += @("--source", $resolvedSource)
        }
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
    }
    "ImportClipboard" {
        $arguments += @("import-clipboard", "--report-dir", $resolvedReportDir, "--report-base", $ReportBase)
        if ($resolvedResponse) {
            $arguments += @("--response", $resolvedResponse)
        }
        if ($resolvedSource) {
            $arguments += @("--source", $resolvedSource)
        }
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
    }
    "Validate" {
        $arguments += @("validate", "--report-dir", $resolvedReportDir, "--report-base", $ReportBase)
        if ($resolvedSource) {
            $arguments += @("--source", $resolvedSource)
        }
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
    }
    "Gate" {
        $arguments += @("gate", "--report-dir", $resolvedReportDir, "--report-base", $ReportBase)
        if ($resolvedSource) {
            $arguments += @("--source", $resolvedSource)
        }
        if ($ScopeKind) {
            $arguments += @("--scope-kind", $ScopeKind)
        }
        if ($ScopeName) {
            $arguments += @("--scope-name", $ScopeName)
        }
    }
}

py -3 @arguments
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    exit $exitCode
}