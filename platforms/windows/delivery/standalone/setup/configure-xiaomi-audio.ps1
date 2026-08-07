[CmdletBinding()]
param(
  [ValidateSet("Install", "Finish", "Repair", "Restore", "Audit", "ValidatePackage")]
  [string] $Mode = "Install",
  [Parameter(Mandatory = $true)]
  [string] $AppPath,
  [string] $DriverZipPath = "",
  [switch] $NonInteractive
)

$ErrorActionPreference = "Stop"
$ProductName = "MiVibe Remote"
$DriverDownloadUrl = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
$ExpectedZipSha256 = "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb"
$StateRoot = Join-Path $env:LOCALAPPDATA "MiVibeRemote\BridgeAudio"
$DriverRoot = Join-Path $StateRoot "VB-CABLE"
$DownloadedDriverZip = Join-Path $StateRoot "VBCABLE_Driver_Pack45.zip"
$PreviousMicFile = Join-Path $StateRoot "previous-default-microphone.txt"
$RebootFlag = Join-Path $StateRoot "reboot-required.flag"
$RunOnceKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$RunOnceName = "MiVibeRemoteAudioFinish"
$ReportPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "MiVibeRemote-audio-check.txt"
$SetupMutex = New-Object Threading.Mutex($false, "Local\MiVibeRemoteAudioSetup")
$OwnsSetupMutex = $false

try {
  $OwnsSetupMutex = $SetupMutex.WaitOne(0)
} catch [Threading.AbandonedMutexException] {
  $OwnsSetupMutex = $true
}

if (-not $OwnsSetupMutex) {
  $message = "语音驱动安装程序已在运行，请完成现有窗口后再试"
  if (-not $NonInteractive) {
    try { (New-Object -ComObject WScript.Shell).Popup($message,0,$ProductName,64)|Out-Null } catch {}
  }
  Write-Output $message
  $SetupMutex.Dispose()
  exit 0
}

function Get-Sha256([string] $Path) {
  $lastError = $null
  for ($attempt = 1; $attempt -le 40; $attempt++) {
    $stream = $null
    $algorithm = $null
    try {
      $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
      $algorithm = [Security.Cryptography.SHA256]::Create()
      return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } catch [IO.IOException] {
      $lastError = $_.Exception
      if ($attempt -lt 40) { Start-Sleep -Milliseconds 250 }
    } finally {
      if ($algorithm) { $algorithm.Dispose() }
      if ($stream) { $stream.Dispose() }
    }
  }
  throw "等待文件解除占用超时：$Path；$($lastError.Message)"
}

function Get-VBCableEndpoint([string] $Flow, [string] $Prefix, [string] $Pattern) {
  $root = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\$Flow"
  foreach ($key in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
    $state = (Get-ItemProperty -LiteralPath $key.PSPath -Name DeviceState -ErrorAction SilentlyContinue).DeviceState
    if ($null -ne $state -and [int] $state -ne 1) { continue }
    $props = Get-ItemProperty -LiteralPath (Join-Path $key.PSPath "Properties") -ErrorAction SilentlyContinue
    $name = "$($props.'{a45c254e-df1c-4efd-8020-67d146a850e0},2') $($props.'{b3f8fa53-0004-438e-9003-51a46e139bfc},6')".Trim()
    if ($name -match $Pattern) {
      return [pscustomobject]@{ Id = "$Prefix.$($key.PSChildName)"; Name = $name }
    }
  }
  return $null
}

function Get-VBCableCapture { Get-VBCableEndpoint "Capture" "{0.0.1.00000000}" "(?i)(^|\s)CABLE Output(\s|$)" }
function Get-VBCableRender { Get-VBCableEndpoint "Render" "{0.0.0.00000000}" "(?i)(^|\s)CABLE Input(\s|$)" }
function Test-VBCableReady { return [bool](Get-VBCableCapture) -and [bool](Get-VBCableRender) }

function Initialize-AudioEndpointApi {
  if ("XiaomiAudioEndpoint" -as [type]) { return }
  Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public enum EDataFlow { eRender = 0, eCapture = 1, eAll = 2 }
public enum ERole { eConsole = 0, eMultimedia = 1, eCommunications = 2 }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] internal class MMDeviceEnumeratorComObject {}
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMMDeviceEnumerator {
  int EnumAudioEndpoints(EDataFlow flow, uint mask, out IntPtr devices);
  int GetDefaultAudioEndpoint(EDataFlow flow, ERole role, out IMMDevice device);
  int GetDevice(string id, out IMMDevice device);
  int RegisterEndpointNotificationCallback(IntPtr client);
  int UnregisterEndpointNotificationCallback(IntPtr client);
}
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMMDevice {
  int Activate(ref Guid iid, uint context, IntPtr args, out IntPtr instance);
  int OpenPropertyStore(uint access, out IntPtr properties);
  int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
  int GetState(out uint state);
}
[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"), ClassInterface(ClassInterfaceType.None)] internal class PolicyConfigClient {}
[ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IPolicyConfig {
  int GetMixFormat(string d, out IntPtr f); int GetDeviceFormat(string d, int x, out IntPtr f);
  int ResetDeviceFormat(string d); int SetDeviceFormat(string d, IntPtr a, IntPtr b);
  int GetProcessingPeriod(string d, int x, out long a, out long b); int SetProcessingPeriod(string d, ref long p);
  int GetShareMode(string d, IntPtr m); int SetShareMode(string d, IntPtr m);
  int GetPropertyValue(string d, IntPtr k, IntPtr v); int SetPropertyValue(string d, IntPtr k, IntPtr v);
  int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string d, ERole role); int SetEndpointVisibility(string d, int v);
}
public static class XiaomiAudioEndpoint {
  public static string GetDefaultCapture() {
    IMMDeviceEnumerator e = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject(); IMMDevice d = null;
    try { int hr=e.GetDefaultAudioEndpoint(EDataFlow.eCapture,ERole.eMultimedia,out d); if(hr!=0)Marshal.ThrowExceptionForHR(hr); string id; hr=d.GetId(out id); if(hr!=0)Marshal.ThrowExceptionForHR(hr); return id; }
    finally { if(d!=null)Marshal.ReleaseComObject(d); Marshal.ReleaseComObject(e); }
  }
  public static void SetDefaultCapture(string id) {
    IPolicyConfig c=(IPolicyConfig)new PolicyConfigClient(); try { for(int r=0;r<3;r++){int hr=c.SetDefaultEndpoint(id,(ERole)r);if(hr!=0)Marshal.ThrowExceptionForHR(hr);} } finally { Marshal.ReleaseComObject(c); }
  }
}
'@
}

function Resolve-DriverPackage {
  if (-not [string]::IsNullOrWhiteSpace($DriverZipPath)) {
    if (-not (Test-Path -LiteralPath $DriverZipPath -PathType Leaf)) {
      throw "VB-CABLE driver package is missing: $DriverZipPath"
    }
    $providedHash = Get-Sha256 $DriverZipPath
    if ($providedHash -ne $ExpectedZipSha256) {
      throw "VB-CABLE package hash mismatch"
    }
    return (Resolve-Path -LiteralPath $DriverZipPath).Path
  }

  if (Test-Path -LiteralPath $DownloadedDriverZip -PathType Leaf) {
    $cachedHash = Get-Sha256 $DownloadedDriverZip
    if ($cachedHash -eq $ExpectedZipSha256) {
      return $DownloadedDriverZip
    }
    Remove-Item -LiteralPath $DownloadedDriverZip -Force
  }

  # Use a process-unique temporary file.  A shared `.download` name allowed a
  # second repair click (or an older helper process) to hash the first process'
  # still-open download.
  $temporary = "$DownloadedDriverZip.$PID.$([Guid]::NewGuid().ToString('N')).download"
  try {
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($curl) {
      & $curl.Source `
        --fail --location --silent --show-error `
        --retry 5 --retry-delay 2 `
        --connect-timeout 30 --max-time 600 `
        --output $temporary $DriverDownloadUrl
      if ($LASTEXITCODE -ne 0) {
        throw "VB-CABLE download failed with curl exit code $LASTEXITCODE"
      }
    } else {
      Invoke-WebRequest -Uri $DriverDownloadUrl -OutFile $temporary -UseBasicParsing -TimeoutSec 600
    }
    $downloadHash = Get-Sha256 $temporary
    if ($downloadHash -ne $ExpectedZipSha256) {
      throw "VB-CABLE download hash mismatch"
    }
    Move-Item -LiteralPath $temporary -Destination $DownloadedDriverZip -Force
    return $DownloadedDriverZip
  } finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
  }
}

function Prepare-DriverFiles {
  $resolvedDriverZip = Resolve-DriverPackage
  $safeRoot = [IO.Path]::GetFullPath($StateRoot).TrimEnd('\') + '\'
  $fullDriverRoot = [IO.Path]::GetFullPath($DriverRoot)
  if (-not $fullDriverRoot.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe driver staging path" }
  if (Test-Path -LiteralPath $fullDriverRoot) { Remove-Item -LiteralPath $fullDriverRoot -Recurse -Force }
  $null = New-Item -ItemType Directory -Force -Path $DriverRoot
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [IO.Compression.ZipFile]::ExtractToDirectory($resolvedDriverZip, $DriverRoot)
  $inf = Join-Path $DriverRoot "vbMmeCable64_win10.inf"
  $cat = Join-Path $DriverRoot "vbaudio_cable64_win10.cat"
  $setup = Join-Path $DriverRoot "VBCABLE_Setup_x64.exe"
  if (-not (Test-Path -LiteralPath $inf) -or -not (Test-Path -LiteralPath $cat) -or -not (Test-Path -LiteralPath $setup)) { throw "Official VB-CABLE setup files are missing" }
  $signature = Get-AuthenticodeSignature -LiteralPath $cat
  $catalogSigner = "$($signature.SignerCertificate.Subject)"
  # Windows hardware catalogs are signed by Microsoft's Hardware
  # Compatibility Publisher, not by the driver vendor whose setup EXE is
  # checked separately below.  Requiring BUREL here incorrectly rejected the
  # genuine catalog from VB-Audio's hash-pinned package.
  if ($signature.Status -ne "Valid" -or $catalogSigner -notmatch "Microsoft Windows Hardware Compatibility Publisher") {
    throw "VB-CABLE catalog signature is invalid (status=$($signature.Status); signer=$catalogSigner)"
  }
  $setupSignature = Get-AuthenticodeSignature -LiteralPath $setup
  $setupSigner = "$($setupSignature.SignerCertificate.Subject)"
  if ($setupSignature.Status -ne "Valid" -or $setupSigner -notmatch "BUREL VINCENT") {
    throw "VB-CABLE official installer signature is invalid (status=$($setupSignature.Status); signer=$setupSigner)"
  }
  return $setup
}

function Confirm-VBCableReady {
  if (-not (Test-VBCableReady)) {
    throw "VB-CABLE endpoints are not available"
  }
}

function Save-DefaultMicrophone {
  try {
    Initialize-AudioEndpointApi
    $id = [XiaomiAudioEndpoint]::GetDefaultCapture()
    if ($id) { Set-Content -LiteralPath $PreviousMicFile -Value $id -Encoding UTF8 }
  } catch {
    Write-Warning "Unable to remember the current default microphone: $($_.Exception.Message)"
  }
}

function Restore-DefaultMicrophone {
  if (-not (Test-Path -LiteralPath $PreviousMicFile -PathType Leaf)) { return }
  try {
    Initialize-AudioEndpointApi
    $id = (Get-Content -LiteralPath $PreviousMicFile -Raw -Encoding UTF8).Trim()
    if ($id) { [XiaomiAudioEndpoint]::SetDefaultCapture($id) }
  } catch {
    Write-Warning "Unable to restore the previous default microphone: $($_.Exception.Message)"
  }
}

function Invoke-OfficialInstaller {
  $setup = Prepare-DriverFiles
  Save-DefaultMicrophone
  # VB-Audio's own documentation requires the extracted x64 setup program to
  # be run as administrator.  Do not emulate a root device with SetupAPI: that
  # bypassed the vendor installer and failed on normal customer machines.
  # Do not request a process handle or wait on the elevated child.  Windows
  # correctly denies a non-elevated helper access to some elevated process
  # handles even though the installer launched successfully.  Observe the
  # audio endpoints below instead.
  Start-Process -FilePath $setup -Verb RunAs
  Set-Content -LiteralPath $RebootFlag -Value "restart Windows to finish VB-CABLE installation" -Encoding ASCII
}

function Wait-VBCable([int] $Seconds) {
  $until = (Get-Date).AddSeconds($Seconds)
  do {
    if (Test-VBCableReady) { return $true }
    Start-Sleep -Milliseconds 1000
  } while ((Get-Date) -lt $until)
  return $false
}

$result = "OK"
$exitCode = 0
try {
  $null = New-Item -ItemType Directory -Force -Path $StateRoot
  switch ($Mode) {
    "Install" {
      if (Test-VBCableReady) {
        Remove-Item -LiteralPath $RebootFlag -Force -ErrorAction SilentlyContinue
      } else {
        # MiVibe installation must remain usable for button mapping even when
        # the optional third-party audio driver is absent.  The user starts the
        # vendor installer explicitly from MiVibe or the Start menu repair item.
        $result = "VB-CABLE is not installed; open MiVibe and click Install/Repair voice driver"
      }
    }
    "Finish" {
      if (Wait-VBCable 60) { Confirm-VBCableReady; Restore-DefaultMicrophone; Remove-Item -LiteralPath $RebootFlag -Force -ErrorAction SilentlyContinue }
      else { $result = "VB-CABLE endpoints are unavailable; run Install/Repair voice driver again" }
    }
    "Repair" {
      if (-not (Test-VBCableReady)) { Invoke-OfficialInstaller }
      if (Wait-VBCable 180) {
        Confirm-VBCableReady
        Restore-DefaultMicrophone
        $result = "VB-CABLE is ready; restart Windows if voice applications cannot see it"
      } else {
        $result = "Official VB-CABLE installer opened; finish Install Driver, restart Windows, then reopen MiVibe"
      }
    }
    "Restore" {
      Restore-DefaultMicrophone
      Remove-ItemProperty -Path $RunOnceKey -Name $RunOnceName -Force -ErrorAction SilentlyContinue
      $result = "Previous microphone restored; VB-CABLE retained"
    }
    "Audit" { if (-not (Test-VBCableReady)) { throw "VB-CABLE is not ready" } }
    "ValidatePackage" {
      $validatedSetup = Prepare-DriverFiles
      $result = "Official VB-CABLE package signatures are valid: $validatedSetup"
    }
  }
} catch {
  $result = "WARNING: $($_.Exception.Message)"
  $exitCode = 1
}

@(
  "MiVibe Remote audio check",
  "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
  "Mode: $Mode",
  "Result: $result",
  "VB-CABLE render: $([bool](Get-VBCableRender))",
  "VB-CABLE capture: $([bool](Get-VBCableCapture))",
  "Driver install: official signed VBCABLE_Setup_x64.exe (user initiated)",
  "System default microphone: preserved when Windows allows restoration",
  "Microphone privacy settings: unchanged",
  "Input method or speech recognition: not included"
) | Set-Content -LiteralPath $ReportPath -Encoding UTF8

if (-not $NonInteractive -and ($Mode -eq "Repair" -or $exitCode -ne 0)) {
  try { (New-Object -ComObject WScript.Shell).Popup($result,0,$ProductName,64)|Out-Null } catch {}
}
Write-Output $result
$SetupMutex.ReleaseMutex()
$SetupMutex.Dispose()
exit $exitCode
