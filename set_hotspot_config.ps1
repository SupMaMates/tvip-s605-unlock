param (
    [string]$Ssid = "TVIP-UNLOCK",
    [string]$Password = "12345678"
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function AwaitAction($WinRtTask) {
    $netTask = $asTaskGeneric.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
}

[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null

$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if ($null -eq $profile) {
    Write-Output "STATUS:NoProfile"
    exit 1
}

$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$config = $manager.GetCurrentAccessPointConfiguration()

$config.Ssid = $Ssid
$config.Passphrase = $Password
AwaitAction ($manager.ConfigureAccessPointAsync($config))

$updated = $manager.GetCurrentAccessPointConfiguration()
Write-Output "STATUS:Success"
Write-Output "SSID:$($updated.Ssid)"
Write-Output "KEY:$($updated.Passphrase)"
