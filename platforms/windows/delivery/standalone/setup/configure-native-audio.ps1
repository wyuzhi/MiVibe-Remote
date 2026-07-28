[CmdletBinding()]
param(
  [ValidateSet("Install", "Repair", "Restore", "Audit")]
  [string] $Mode = "Install",
  [Parameter(Mandatory = $true)]
  [string] $ProductId,
  [Parameter(Mandatory = $true)]
  [string] $ProductName,
  [Parameter(Mandatory = $true)]
  [string] $EndpointPattern
)

$ErrorActionPreference = "Stop"
$StateRoot = Join-Path $env:LOCALAPPDATA ("2655AI\BridgeAudio\" + $ProductId)
$PreviousMicFile = Join-Path $StateRoot "previous-default-microphone.txt"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ReportPath = Join-Path $Desktop ("{0}-audio-check.txt" -f $ProductName)

function Initialize-AudioEndpointApi {
  if ("BridgeAudioEndpoint" -as [type]) { return }
  Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public enum EDataFlow { eRender = 0, eCapture = 1, eAll = 2 }
public enum ERole { eConsole = 0, eMultimedia = 1, eCommunications = 2 }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
internal class MMDeviceEnumeratorComObject {}
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMMDeviceEnumerator {
  int EnumAudioEndpoints(EDataFlow flow, uint mask, out IntPtr devices);
  int GetDefaultAudioEndpoint(EDataFlow flow, ERole role, out IMMDevice device);
  int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
  int RegisterEndpointNotificationCallback(IntPtr client);
  int UnregisterEndpointNotificationCallback(IntPtr client);
}
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMMDevice {
  int Activate(ref Guid iid, uint context, IntPtr activationParams, out IntPtr instance);
  int OpenPropertyStore(uint access, out IntPtr properties);
  int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
  int GetState(out uint state);
}
[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"), ClassInterface(ClassInterfaceType.None)]
internal class PolicyConfigClient {}
[ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IPolicyConfig {
  int GetMixFormat(string device, out IntPtr format);
  int GetDeviceFormat(string device, int isDefault, out IntPtr format);
  int ResetDeviceFormat(string device);
  int SetDeviceFormat(string device, IntPtr endpointFormat, IntPtr mixFormat);
  int GetProcessingPeriod(string device, int isDefault, out long defaultPeriod, out long minimumPeriod);
  int SetProcessingPeriod(string device, ref long period);
  int GetShareMode(string device, IntPtr mode);
  int SetShareMode(string device, IntPtr mode);
  int GetPropertyValue(string device, IntPtr key, IntPtr value);
  int SetPropertyValue(string device, IntPtr key, IntPtr value);
  int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string device, ERole role);
  int SetEndpointVisibility(string device, int visible);
}
public static class BridgeAudioEndpoint {
  public static string GetDefaultCapture() {
    IMMDeviceEnumerator enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
    IMMDevice device = null;
    try {
      int hr = enumerator.GetDefaultAudioEndpoint(EDataFlow.eCapture, ERole.eMultimedia, out device);
      if (hr != 0) Marshal.ThrowExceptionForHR(hr);
      string id;
      hr = device.GetId(out id);
      if (hr != 0) Marshal.ThrowExceptionForHR(hr);
      return id;
    } finally {
      if (device != null) Marshal.ReleaseComObject(device);
      Marshal.ReleaseComObject(enumerator);
    }
  }
  public static void SetDefaultCapture(string id) {
    IPolicyConfig config = (IPolicyConfig)new PolicyConfigClient();
    try {
      for (int role = 0; role < 3; role++) {
        int hr = config.SetDefaultEndpoint(id, (ERole)role);
        if (hr != 0) Marshal.ThrowExceptionForHR(hr);
      }
    } finally { Marshal.ReleaseComObject(config); }
  }
}
'@
}

function Get-CaptureEndpoint([string] $Pattern) {
  $root = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
  foreach ($key in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
    $state = (Get-ItemProperty -LiteralPath $key.PSPath -Name DeviceState -ErrorAction SilentlyContinue).DeviceState
    if ($null -ne $state -and [int] $state -ne 1) { continue }
    $properties = Join-Path $key.PSPath "Properties"
    $props = Get-ItemProperty -LiteralPath $properties -ErrorAction SilentlyContinue
    $name = "$($props.'{a45c254e-df1c-4efd-8020-67d146a850e0},2') $($props.'{b3f8fa53-0004-438e-9003-51a46e139bfc},6')".Trim()
    if ($name -match $Pattern) {
      return [pscustomobject]@{
        Id = "{0.0.1.00000000}.$($key.PSChildName)"
        Name = $name
      }
    }
  }
  return $null
}

function Enable-DesktopMicrophoneAccess {
  $root = "HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
  $desktopApps = Join-Path $root "NonPackaged"
  $null = New-Item -ItemType Directory -Force -Path $root, $desktopApps
  Set-ItemProperty -LiteralPath $root -Name Value -Value Allow -Type String
  Set-ItemProperty -LiteralPath $desktopApps -Name Value -Value Allow -Type String
}

function Set-NativeMicrophone {
  $endpoint = Get-CaptureEndpoint $EndpointPattern
  if (-not $endpoint) {
    throw "Windows did not find the device microphone. Plug in the receiver and run Repair again."
  }
  Initialize-AudioEndpointApi
  $current = [BridgeAudioEndpoint]::GetDefaultCapture()
  if (-not (Test-Path -LiteralPath $PreviousMicFile) -and $current -ne $endpoint.Id) {
    $null = New-Item -ItemType Directory -Force -Path $StateRoot
    Set-Content -LiteralPath $PreviousMicFile -Value $current -Encoding UTF8
  }
  [BridgeAudioEndpoint]::SetDefaultCapture($endpoint.Id)
  Enable-DesktopMicrophoneAccess
  return $endpoint
}

function Restore-PreviousMicrophone {
  if (-not (Test-Path -LiteralPath $PreviousMicFile)) { return }
  Initialize-AudioEndpointApi
  $endpoint = (Get-Content -LiteralPath $PreviousMicFile -Raw -Encoding UTF8).Trim()
  if ($endpoint) { [BridgeAudioEndpoint]::SetDefaultCapture($endpoint) }
  Remove-Item -LiteralPath $PreviousMicFile -Force -ErrorAction SilentlyContinue
}

$result = "OK"
$endpointName = ""
try {
  $null = New-Item -ItemType Directory -Force -Path $StateRoot
  switch ($Mode) {
    "Install" { $endpointName = (Set-NativeMicrophone).Name }
    "Repair" { $endpointName = (Set-NativeMicrophone).Name }
    "Restore" { Restore-PreviousMicrophone; $result = "Previous microphone restored" }
    "Audit" {
      $endpoint = Get-CaptureEndpoint $EndpointPattern
      if (-not $endpoint) { throw "Device microphone is not present" }
      $endpointName = $endpoint.Name
    }
  }
} catch {
  $result = "WARNING: $($_.Exception.Message)"
}

@(
  $ProductName,
  "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
  "Mode: $Mode",
  "Result: $result",
  "Native microphone: $(if ($endpointName) { $endpointName } else { 'not found' })",
  "Virtual audio driver: not required",
  "Input method or speech recognition: not included"
) | Set-Content -LiteralPath $ReportPath -Encoding UTF8

if ($Mode -eq "Repair") {
  try { (New-Object -ComObject WScript.Shell).Popup($result, 0, $ProductName, 64) | Out-Null } catch {}
}
exit 0
