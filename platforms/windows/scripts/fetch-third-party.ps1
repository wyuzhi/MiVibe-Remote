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
