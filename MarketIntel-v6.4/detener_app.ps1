$ErrorActionPreference = 'Stop'
try {
    $folder = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    $dataFolder = if ($env:MARKETINTEL_DATA_DIR) { [IO.Path]::GetFullPath($env:MARKETINTEL_DATA_DIR) } else { Join-Path $env:LOCALAPPDATA 'MarketIntel' }
    $records = @(Get-ChildItem -LiteralPath $dataFolder -Filter 'servidor-*.json' -ErrorAction SilentlyContinue)
    $matched = $null
    foreach ($file in $records) {
        try { $record = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } catch { continue }
        if ($record.directory -and [string]::Equals(([IO.Path]::GetFullPath($record.directory)).TrimEnd('\'), $folder, [StringComparison]::OrdinalIgnoreCase)) {
            $matched = @{ Data = $record; File = $file.FullName }
            break
        }
    }
    if (-not $matched) { throw 'No hay un servidor registrado por el acceso directo de esta carpeta. Si lo abriste con INICIAR.bat, cierra su ventana de consola.' }
    $record = $matched.Data
    if ([string]$record.install_id -notmatch '^[a-f0-9]{16}$' -or [string]$record.launcher_token -notmatch '^[a-f0-9]{32}$') { throw 'El registro del servidor no es valido. No se detuvo ningun proceso.' }
    if ([int]$record.pid -le 0 -or [int]$record.port -lt 1 -or [int]$record.port -gt 65535 -or -not $record.start_filetime) { throw 'Faltan datos para identificar el proceso de forma segura.' }
    $serverPath = Join-Path $folder 'servidor.py'
    if (-not [string]::Equals([IO.Path]::GetFullPath($record.server), $serverPath, [StringComparison]::OrdinalIgnoreCase)) { throw 'El registro corresponde a otro archivo. No se detuvo ningun proceso.' }
    $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$record.pid)
    if (-not $process) {
        Remove-Item -LiteralPath $matched.File -Force
        throw 'Ese servidor ya esta cerrado. Puedes actualizar la carpeta.'
    }
    if (-not $process.ExecutablePath -or -not [string]::Equals([IO.Path]::GetFullPath($process.ExecutablePath), [IO.Path]::GetFullPath($record.python), [StringComparison]::OrdinalIgnoreCase)) { throw 'Ese PID ya no pertenece al Python registrado. No se detuvo ningun proceso.' }
    # Exact argument boundaries accept both quoted paths and paths without spaces.
    $serverArgument = '(?i)(?:^|\s)(?:"' + [regex]::Escape($serverPath) + '"|' + [regex]::Escape($serverPath) + ')(?=\s|$)'
    $tokenArgument = '(?:^|\s)--marketintel-launcher-token\s+' + [regex]::Escape([string]$record.launcher_token) + '(?=\s|$)'
    if ($process.CommandLine -notmatch $serverArgument -or $process.CommandLine -notmatch $tokenArgument) { throw 'El comando del proceso no coincide con este acceso directo. No se detuvo ningun proceso.' }
    $actualStart = [long]($process.CreationDate.ToUniversalTime().ToFileTimeUtc())
    $recordedStart = [long]::Parse([string]$record.start_filetime)
    if ([Math]::Abs($actualStart - $recordedStart) -gt 10000) { throw 'El PID fue reutilizado por otro proceso. No se detuvo ningun proceso.' }
    $health = Invoke-RestMethod -Uri ('http://127.0.0.1:' + [int]$record.port + '/health') -TimeoutSec 3
    if ($health.service -ne 'MarketIntel' -or $health.install_id -ne $record.install_id -or $health.version -ne $record.version) { throw 'El servidor del puerto no coincide con la carpeta y version registradas. No se detuvo ningun proceso.' }
    Stop-Process -Id ([int]$record.pid) -ErrorAction Stop
    Remove-Item -LiteralPath $matched.File -Force
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('El servidor de esta carpeta de MarketIntel se detuvo. Ya puedes actualizar o mover la carpeta.', 'MarketIntel') | Out-Null
    exit 0
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'MarketIntel') | Out-Null
    exit 1
}
