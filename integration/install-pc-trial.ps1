param(
    [string]$Driver,
    [string]$ExpectedSha256,
    [string]$BackupDirectory,
    [switch]$Rollback
)
$ErrorActionPreference = 'Stop'
if (Get-Process vrserver -ErrorAction SilentlyContinue) { throw 'Close SteamVR before updating the driver.' }
if (!$BackupDirectory) { throw 'Specify a private backup directory.' }
$backup = [IO.Path]::GetFullPath($BackupDirectory)
$data = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'QuestLHSync'
$target = Join-Path $data 'questlhsync/bin/win64/driver_questlhsync.dll'
$paths = Get-Content -LiteralPath (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'openvr/openvrpaths.vrpath') -Raw | ConvertFrom-Json
$settingsPath = Join-Path $paths.config[0] 'steamvr.vrsettings'
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$manifest = Join-Path $backup 'pc-update.json'
if ($Rollback) {
    $saved = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    if ($saved.target -ne $target -or $saved.settings -ne $settingsPath) { throw 'Backup targets do not match this installation.' }
    $old = Join-Path $backup 'pc-driver-before.dll'
    if ((Get-FileHash -LiteralPath $old).Hash -ne $saved.sha256) { throw 'Backup driver checksum mismatch.' }
    Copy-Item -LiteralPath $old -Destination $target -Force
    if ($saved.hadSection) { $settings | Add-Member -NotePropertyName driver_questlhsync -NotePropertyValue $saved.section -Force }
    else { $settings.PSObject.Properties.Remove('driver_questlhsync') }
} else {
    if (!$Driver -or $ExpectedSha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Specify the reviewed driver and SHA256.' }
    if ((Get-FileHash -LiteralPath $Driver).Hash -ne $ExpectedSha256) { throw 'Driver does not match the reviewed build.' }
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    if (!(Test-Path -LiteralPath $manifest)) {
        Copy-Item -LiteralPath $target -Destination (Join-Path $backup 'pc-driver-before.dll')
        $saved = [ordered]@{target=$target; settings=$settingsPath; sha256=(Get-FileHash -LiteralPath $target).Hash;
            hadSection=($null -ne $settings.driver_questlhsync); section=$settings.driver_questlhsync}
        [IO.File]::WriteAllText($manifest, ($saved | ConvertTo-Json -Depth 50))
    } else {
        $saved = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        if ($saved.target -ne $target -or $saved.settings -ne $settingsPath) { throw 'Backup targets do not match this installation.' }
    }
    Copy-Item -LiteralPath $Driver -Destination $target -Force
    if (!$settings.driver_questlhsync) { $settings | Add-Member -NotePropertyName driver_questlhsync -NotePropertyValue ([pscustomobject]@{}) }
    foreach ($item in @{enable=$true; anyHmd=$true; profile='galaxy-xr-factory-trial'}.GetEnumerator()) {
        $settings.driver_questlhsync | Add-Member -NotePropertyName $item.Key -NotePropertyValue $item.Value -Force
    }
}
$temporary = $settingsPath + '.gxr-update.tmp'
[IO.File]::WriteAllText($temporary, ($settings | ConvertTo-Json -Depth 100))
Move-Item -LiteralPath $temporary -Destination $settingsPath -Force
if ($Rollback) { Write-Host 'Previous driver and QuestLHSync settings restored.' }
else { Write-Host 'PC compatibility driver updated. Factory trial uses its own state directory.' }
