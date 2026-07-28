[CmdletBinding()]
param([Parameter(Mandatory = $true)][string] $AppPath)
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($AppPath).TrimEnd('\') + '\'
Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and ([IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
exit 0
