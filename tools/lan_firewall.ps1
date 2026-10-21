param(
    [Parameter(Mandatory = $true)][ValidateSet('add','remove')][string]$Action,
    [Parameter(Mandatory = $true)][string]$ServerAddress,
    [Parameter(Mandatory = $true)][string]$ClientAddress,
    [Parameter(Mandatory = $true)][ValidateRange(1024,65535)][int]$Port,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Session
)

$ErrorActionPreference = 'Stop'
foreach ($address in @($ServerAddress, $ClientAddress)) {
    $parsed = [Net.IPAddress]::Parse($address)
    if ($parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        $parsed.ToString() -cne $address -or [Net.IPAddress]::IsLoopback($parsed) -or
        $parsed.GetAddressBytes()[0] -eq 0 -or $parsed.GetAddressBytes()[0] -ge 224) { throw 'Unicast IPv4 required' }
}
if ($ServerAddress -eq $ClientAddress) { throw 'Distinct addresses required' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'),
        '-Action', $Action, '-ServerAddress', $ServerAddress, '-ClientAddress', $ClientAddress,
        '-Port', [string]$Port, '-Session', $Session)
    $process = Start-Process -FilePath (Get-Process -Id $PID).Path -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList $arguments
    exit $process.ExitCode
}
$name = "Kiosk-LAN-Wizard-$Session"
$existing = @(Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue)
if ($Action -eq 'add') {
    if ($existing.Count) { throw 'Rule already exists; not owned by this invocation' }
    try {
        $null = New-NetFirewallRule -Name $name -DisplayName $name -Group 'Kiosk disposable LAN wizard' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $ServerAddress -LocalPort $Port -RemoteAddress $ClientAddress -Profile Any
    } catch {
        $created = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
        if ($created -and $created.Group -eq 'Kiosk disposable LAN wizard') { $created | Remove-NetFirewallRule }
        throw 'Cannot create temporary rule'
    }
} elseif ($existing.Count) {
    if ($existing.Count -ne 1 -or $existing[0].Group -ne 'Kiosk disposable LAN wizard' -or $existing[0].DisplayName -ne $name) { throw 'Unexpected rule ownership' }
    $addresses = $existing[0] | Get-NetFirewallAddressFilter
    $ports = $existing[0] | Get-NetFirewallPortFilter
    if (($addresses.LocalAddress -join ',') -ne $ServerAddress -or ($addresses.RemoteAddress -join ',') -ne $ClientAddress -or
        [string]$ports.LocalPort -ne [string]$Port -or [string]$ports.Protocol -notin @('TCP','6')) { throw 'Unexpected rule scope' }
    $existing[0] | Remove-NetFirewallRule
}
if ($Action -eq 'remove' -and (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue)) { throw 'Rule removal not verified' }
