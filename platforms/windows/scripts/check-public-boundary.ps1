[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot

Push-Location $Project
try {
  $files = @(git ls-files --cached --others --exclude-standard)
  if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate repository files" }

  $errors = [Collections.Generic.List[string]]::new()
  $forbiddenPathPatterns = @(
    '(?i)(^|/)source/licensing(/|$)',
    '(?i)(^|/)(customer_entry|customer_license)\.py$',
    '(?i)(^|/).*hardened.*\.(py|ps1|spec)$',
    '(?i)(^|/)(private|customer-data)(/|$)'
  )
  $forbiddenBinaryExtensions = @(
    '.exe', '.dll', '.pyd', '.zip', '.xz', '.jpg', '.jpeg', '.png'
  )

  foreach ($file in $files) {
    $normalized = $file.Replace('\', '/')
    foreach ($pattern in $forbiddenPathPatterns) {
      if ($normalized -match $pattern) {
        $errors.Add("forbidden path: $normalized")
        break
      }
    }
    if ([IO.Path]::GetExtension($normalized).ToLowerInvariant() -in $forbiddenBinaryExtensions) {
      $errors.Add("binary asset must be fetched or attached to a Release, not committed: $normalized")
    }
  }

  $textExtensions = @(
    '.py', '.ps1', '.md', '.txt', '.json', '.yml', '.yaml', '.iss', '.spec', '.toml'
  )
  foreach ($file in $files) {
    $normalized = $file.Replace('\', '/')
    if ($normalized -eq 'scripts/check-public-boundary.ps1') { continue }
    if ([IO.Path]::GetExtension($normalized).ToLowerInvariant() -notin $textExtensions) { continue }
    $path = Join-Path $Project $file
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8

    if ($text -match '(?i)(?:[A-Z]:\\Users\\[^\\\r\n]+|[A-Z]:\\[^\r\n]*(?:手搓项目|2655-Tools))') {
      $errors.Add("personal absolute path: $normalized")
    }
    if ($text -match '(?im)^\s*(?:from|import)\s+(?:licensing|customer_license|customer_entry)\b') {
      $errors.Add("private licensing import: $normalized")
    }
    if ($text -match '(?i)(?:license-api|xorp[a-z]*)') {
      $errors.Add("private service marker: $normalized")
    }
    $macMatches = [regex]::Matches(
      $text,
      '(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])'
    )
    foreach ($match in $macMatches) {
      if ($match.Value.ToUpperInvariant() -ne 'AA:BB:CC:DD:EE:FF') {
        $errors.Add("device address literal: $normalized")
      }
    }
    if ($text -match '(?i)(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*["''][^"'']{8,}["'']') {
      $errors.Add("possible credential: $normalized")
    }
  }

  if ($errors.Count -gt 0) {
    $errors | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    exit 1
  }
  Write-Host "Public boundary check passed for $($files.Count) files."
}
finally {
  Pop-Location
}
