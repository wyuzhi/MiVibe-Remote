[CmdletBinding()]
param(
  [switch] $Force
)

$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot

function Get-SHA256([string] $Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-VerifiedAsset(
  [string] $Name,
  [string] $Url,
  [string] $Destination,
  [string] $ExpectedSha256
) {
  $parent = Split-Path -Parent $Destination
  $null = New-Item -ItemType Directory -Force -Path $parent

  if ((-not $Force) -and (Test-Path -LiteralPath $Destination -PathType Leaf)) {
    $currentHash = Get-SHA256 $Destination
    if ($currentHash -eq $ExpectedSha256) {
      Write-Host "$Name already verified: $currentHash"
      return
    }
  }

  $temporary = "$Destination.download"
  if ($Force -and (Test-Path -LiteralPath $temporary)) {
    Remove-Item -LiteralPath $temporary -Force
  }
  try {
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($curl) {
      $curlArguments = @(
        '--fail', '--location', '--silent', '--show-error',
        '--retry', '5', '--retry-delay', '2',
        '--connect-timeout', '30', '--max-time', '600'
      )
      if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        $curlArguments += @('--continue-at', '-')
      }
      $curlArguments += @('--output', $temporary, $Url)
      & $curl.Source @curlArguments
      if ($LASTEXITCODE -ne 0) {
        throw "$Name download failed with curl exit code $LASTEXITCODE"
      }
    }
    else {
      Invoke-WebRequest -Uri $Url -OutFile $temporary -UseBasicParsing -TimeoutSec 600
    }
    $downloadHash = Get-SHA256 $temporary
    if ($downloadHash -ne $ExpectedSha256) {
      throw "$Name checksum mismatch: expected $ExpectedSha256, got $downloadHash"
    }
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
    Write-Host "$Name downloaded and verified: $downloadHash"
  }
  finally {
    if (Test-Path -LiteralPath $temporary) {
      Remove-Item -LiteralPath $temporary -Force
    }
  }
}

function Get-VerifiedZipEntry(
  [string] $Archive,
  [string] $EntryName,
  [string] $Destination,
  [string] $ExpectedSha256
) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $parent = Split-Path -Parent $Destination
  $null = New-Item -ItemType Directory -Force -Path $parent
  if ((-not $Force) -and (Test-Path -LiteralPath $Destination -PathType Leaf)) {
    $currentHash = Get-SHA256 $Destination
    if ($currentHash -eq $ExpectedSha256) {
      Write-Host "$EntryName already verified: $currentHash"
      return
    }
  }

  $temporary = "$Destination.extracting"
  $archiveHandle = [IO.Compression.ZipFile]::OpenRead($Archive)
  try {
    $entry = $archiveHandle.GetEntry($EntryName)
    if (-not $entry) { throw "Missing verified archive entry: $EntryName" }
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $temporary, $true)
  }
  finally {
    $archiveHandle.Dispose()
  }
  $extractedHash = Get-SHA256 $temporary
  if ($extractedHash -ne $ExpectedSha256) {
    throw "$EntryName checksum mismatch: expected $ExpectedSha256, got $extractedHash"
  }
  Move-Item -LiteralPath $temporary -Destination $Destination -Force
  Write-Host "$EntryName extracted and verified: $extractedHash"
}

Get-VerifiedAsset `
  -Name "Frida Gadget 17.15.3" `
  -Url "https://github.com/frida/frida/releases/download/17.15.3/frida-gadget-17.15.3-windows-x86_64.dll.xz" `
  -Destination (Join-Path $Project "source\bridges\xiaomi\assets\frida-gadget-17.15.3-windows-x86_64.dll.xz") `
  -ExpectedSha256 "B566D70189B6D551AD8F4E0BEA24DE08A3D4C0F559BB35B2BDB67D45182240C2"

Get-VerifiedAsset `
  -Name "Frida core license" `
  -Url "https://raw.githubusercontent.com/frida/frida-core/main/COPYING" `
  -Destination (Join-Path $Project "delivery\vendor\frida-COPYING.txt") `
  -ExpectedSha256 "5EA1544B51A28BC823B03159190D4108F9FB4F4EF912389F5137C6D295E175B2"

$WinSparkleArchive = Join-Path $Project "delivery\vendor\winsparkle\WinSparkle-0.9.4.zip"
Get-VerifiedAsset `
  -Name "WinSparkle 0.9.4 binary distribution" `
  -Url "https://github.com/vslavik/winsparkle/releases/download/v0.9.4/WinSparkle-0.9.4.zip" `
  -Destination $WinSparkleArchive `
  -ExpectedSha256 "6037DF37FC263BD1650A1C4949681A9D40FFE991D01F35892A406CB5D103C976"

Get-VerifiedZipEntry `
  -Archive $WinSparkleArchive `
  -EntryName "WinSparkle-0.9.4/x64/Release/WinSparkle.dll" `
  -Destination (Join-Path $Project "delivery\vendor\winsparkle\WinSparkle.dll") `
  -ExpectedSha256 "9B43B1C16EE39FB9A91B5BD75138767898779510E0836BE2919250607CDBE8AB"

Get-VerifiedZipEntry `
  -Archive $WinSparkleArchive `
  -EntryName "WinSparkle-0.9.4/bin/winsparkle-tool.exe" `
  -Destination (Join-Path $Project "delivery\vendor\winsparkle\winsparkle-tool.exe") `
  -ExpectedSha256 "0C5412C481BE6146313A2AF46CCE4A928913C94754763A75BB11EF15C9097CC3"

Get-VerifiedZipEntry `
  -Archive $WinSparkleArchive `
  -EntryName "WinSparkle-0.9.4/COPYING" `
  -Destination (Join-Path $Project "delivery\vendor\winsparkle\COPYING") `
  -ExpectedSha256 "599D22B139B44F8F17140D09D16A4DD1FD6C864616135210B9308C7810D49CAF"

Get-VerifiedZipEntry `
  -Archive $WinSparkleArchive `
  -EntryName "WinSparkle-0.9.4/COPYING.expat" `
  -Destination (Join-Path $Project "delivery\vendor\winsparkle\COPYING.expat") `
  -ExpectedSha256 "31B15DE82AA19A845156169A17A5488BF597E561B2C318D159ED583139B25E87"
