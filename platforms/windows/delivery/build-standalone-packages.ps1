[CmdletBinding()]
param(
  [string] $Version = "0.1.8",
  [string[]] $Product = @("xiaomi"),
  [switch] $AllowUnsignedCandidate,
  [string] $PythonExecutable = "",
  [string] $InnoCompilerPath = "",
  [switch] $SkipThirdPartyFetch
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $Project "build\standalone"
$Dist = Join-Path $Stage "dist"
$Work = Join-Path $Stage "work"
$Output = Join-Path $PSScriptRoot "out\standalone"

function Resolve-Executable([string] $Requested, [string[]] $Candidates, [string] $Label) {
  foreach ($candidate in @($Requested) + $Candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
    $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($command) { return $command.Source }
  }
  throw "Unable to find $Label. Pass its path explicitly."
}

$innoCandidates = @("ISCC.exe")
if (${env:ProgramFiles(x86)}) {
  $innoCandidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if ($env:ProgramFiles) {
  $innoCandidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
}

$BuildPython = Resolve-Executable $PythonExecutable @("python.exe", "python") "Python 3.12"
$InnoCompiler = Resolve-Executable $InnoCompilerPath $innoCandidates "Inno Setup 6 compiler"

function Reset-SafeDirectory([string] $Path, [string] $AllowedRoot) {
  $fullPath = [IO.Path]::GetFullPath($Path)
  $fullRoot = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\') + '\'
  if (-not $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean outside allowed root: $fullPath"
  }
  if (Test-Path -LiteralPath $fullPath) {
    Remove-Item -LiteralPath $fullPath -Recurse -Force
  }
  $null = New-Item -ItemType Directory -Force -Path $fullPath
}

function Get-SHA256([string] $Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if ($Version -notmatch '^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)(?:\.(?<build>\d+))?(?:-[0-9A-Za-z.-]+)?$') {
  throw "Invalid version: $Version"
}
$VersionInfoVersion = @(
  [int] $Matches.major,
  [int] $Matches.minor,
  [int] $Matches.patch,
  $(if ($Matches.build) { [int] $Matches.build } else { 0 })
) -join '.'

$productCatalog = @{
  xiaomi = [pscustomobject]@{
    Id = "xiaomi"
    Spec = "XiaomiRemoteBridge.spec"
    Folder = "MiVibeRemote"
    Exe = "MiVibeRemote.exe"
    Setup = "XiaomiRemoteBridgeSetup.iss"
    Entry = "source\standalone\xiaomi_main.py"
    OutputPrefix = "MiVibeRemoteSetup"
  }
  t1 = [pscustomobject]@{
    Id = "t1"
    Spec = "T1RemoteBridge.spec"
    Folder = "T1RemoteBridge"
    Exe = "T1RemoteBridge.exe"
    Setup = "T1RemoteBridgeSetup.iss"
    Entry = "source\standalone\t1_main.py"
    OutputPrefix = "T1RemoteBridgeSetup"
  }
  v60 = [pscustomobject]@{
    Id = "v60"
    Spec = "V60PenBridge.spec"
    Folder = "V60PenBridge"
    Exe = "V60PenBridge.exe"
    Setup = "V60PenBridgeSetup.iss"
    Entry = "source\standalone\v60_main.py"
    OutputPrefix = "V60PenBridgeSetup"
  }
}
$unknownProducts = @($Product | Where-Object { -not $productCatalog.ContainsKey($_) })
if ($unknownProducts.Count -gt 0) {
  throw "Unsupported product: $($unknownProducts -join ', '). Expected xiaomi, t1, or v60."
}
$selectedProducts = @($Product | Select-Object -Unique | ForEach-Object {
  $productCatalog[$_]
})

& (Join-Path $Project "scripts\check-public-boundary.ps1")
if ($LASTEXITCODE -ne 0) { throw "Public boundary check failed: $LASTEXITCODE" }

if (-not $SkipThirdPartyFetch) {
  & (Join-Path $Project "scripts\fetch-third-party.ps1")
  if ($LASTEXITCODE -ne 0) { throw "Third-party asset fetch failed: $LASTEXITCODE" }
}

foreach ($productDefinition in $selectedProducts) {
  $text = Get-Content -LiteralPath (Join-Path $Project $productDefinition.Entry) -Raw -Encoding UTF8
  if (-not $text.Contains(('APP_VERSION = "{0}"' -f $Version))) {
    throw "Standalone version is not synchronized: $($productDefinition.Entry)"
  }
}

& $BuildPython -m unittest discover -s (Join-Path $Project "tests") -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Automated tests failed: $LASTEXITCODE" }

Reset-SafeDirectory $Stage (Join-Path $Project "build")
Reset-SafeDirectory $Output (Join-Path $PSScriptRoot "out")

foreach ($productDefinition in $selectedProducts) {
  $productWork = Join-Path $Work $productDefinition.Id
  $null = New-Item -ItemType Directory -Force -Path $productWork
  & $BuildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $Dist `
    --workpath $productWork `
    (Join-Path $Project ("source\" + $productDefinition.Spec))
  if ($LASTEXITCODE -ne 0) { throw "$($productDefinition.Id) PyInstaller build failed: $LASTEXITCODE" }
}

foreach ($productDefinition in $selectedProducts) {
  $folder = Join-Path $Dist $productDefinition.Folder
  $exe = Join-Path $folder $productDefinition.Exe
  if (-not (Test-Path -LiteralPath $exe)) { throw "Missing built executable: $exe" }
  $leaks = @(Get-ChildItem -LiteralPath $folder -Recurse -File | Where-Object {
    $_.Extension -in @('.py', '.pyc', '.pyo', '.spec')
  })
  if ($leaks.Count -gt 0) { throw "$($productDefinition.Id) package contains source files: $($leaks.FullName -join ', ')" }
  $archiveListing = (& $BuildPython -m PyInstaller.utils.cliutils.archive_viewer -r -b $exe 2>&1) -join "`n"
  if ($LASTEXITCODE -ne 0) { throw "Unable to inspect $exe" }
  if ($archiveListing -match '(?i)streaming[-_.]?voice[-_.]?input|input[-_.]?method|speech[-_.]?recogn') {
    throw "$($productDefinition.Id) package contains input-method or speech-recognition code"
  }
  if ($archiveListing -match '(?i)customer_(entry|license)|\blicensing(?:[.\\/]|$)|hardened|nuitka') {
    throw "$($productDefinition.Id) package contains licensing or anti-reversing code"
  }
  if ($productDefinition.Id -eq 'xiaomi' -and $archiveListing -match 'bridges\.(t1|hanvon)') {
    throw "Xiaomi package contains another hardware bridge"
  }
  if ($productDefinition.Id -eq 't1' -and $archiveListing -match 'bridges\.(xiaomi|hanvon|audio\.audio_router)') {
    throw "T1 package contains another bridge or virtual audio router"
  }
  if ($productDefinition.Id -eq 'v60' -and $archiveListing -match 'bridges\.(xiaomi|t1|audio\.audio_router)') {
    throw "V60 package contains another bridge or virtual audio router"
  }
  if ($productDefinition.Id -in @('t1','v60')) {
    $forbiddenFiles = @(Get-ChildItem -LiteralPath $folder -Recurse -File | Where-Object {
      $_.Name -match '(?i)vbcable|portaudio|sounddevice|numpy|frida|winrt'
    })
    if ($forbiddenFiles.Count -gt 0) {
      throw "$($productDefinition.Id) package contains virtual-audio or Xiaomi-only files: $($forbiddenFiles.FullName -join ', ')"
    }
  }
  $signature = Get-AuthenticodeSignature -LiteralPath $exe
  if (-not $AllowUnsignedCandidate -and $signature.Status -ne 'Valid') {
    throw "$($productDefinition.Id) executable is unsigned; use -AllowUnsignedCandidate only for local candidates"
  }
}

$SetupRoot = Join-Path $PSScriptRoot "standalone\setup"
foreach ($productDefinition in $selectedProducts) {
  $folder = Join-Path $Dist $productDefinition.Folder
  & $InnoCompiler `
    "/DAppVersion=$Version" `
    "/DVersionInfoVersion=$VersionInfoVersion" `
    "/DSourceDir=$folder" `
    "/DOutputDir=$Output" `
    (Join-Path $SetupRoot $productDefinition.Setup)
  if ($LASTEXITCODE -ne 0) { throw "$($productDefinition.Id) installer build failed: $LASTEXITCODE" }
}

$results = foreach ($productDefinition in $selectedProducts) {
  $setup = Get-ChildItem -LiteralPath $Output -File -Filter "$($productDefinition.OutputPrefix)-*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $setup) { throw "Missing setup for $($productDefinition.Id)" }
  $setupHash = Get-SHA256 $setup.FullName
  $checksumPath = "$($setup.FullName).sha256"
  [IO.File]::WriteAllText(
    $checksumPath,
    "$setupHash  $($setup.Name)`n",
    [Text.Encoding]::ASCII
  )
  $setupSignature = Get-AuthenticodeSignature -LiteralPath $setup.FullName
  if (-not $AllowUnsignedCandidate -and $setupSignature.Status -ne 'Valid') {
    throw "$($productDefinition.Id) installer is unsigned"
  }
  [pscustomobject]@{
    Product = $productDefinition.Id
    Setup = $setup.FullName
    Bytes = $setup.Length
    SHA256 = $setupHash
    Checksum = $checksumPath
    ExecutableAuthenticode = (Get-AuthenticodeSignature -LiteralPath (Join-Path $Dist $productDefinition.Folder $productDefinition.Exe)).Status.ToString()
    SetupAuthenticode = $setupSignature.Status.ToString()
  }
}

$results | Format-List
