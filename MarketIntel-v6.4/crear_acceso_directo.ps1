$ErrorActionPreference = 'Stop'

try {
    $appDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
    $launcherFile = Join-Path $appDirectory 'iniciar_app.py'
    if (-not (Test-Path -LiteralPath $launcherFile -PathType Leaf)) {
        throw 'Falta iniciar_app.py. Extrae el paquete completo antes de crear el acceso directo.'
    }

    $pythonPath = $null
    $pythonCommands = @(
        @{ Name = 'py.exe'; Arguments = @('-3') },
        @{ Name = 'python.exe'; Arguments = @() }
    )
    foreach ($candidate in $pythonCommands) {
        $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $arguments = @($candidate.Arguments) + @('-c', 'import sys; assert sys.version_info >= (3,10); print(sys.executable)')
        $result = & $command.Source @arguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) {
            $path = ([string]($result | Select-Object -Last 1)).Trim()
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $pythonPath = $path
                break
            }
        }
    }
    if (-not $pythonPath) {
        throw 'Instala Python 3.10 o posterior desde python.org (incluye el lanzador py) y vuelve a ejecutar CREAR_ACCESO_DIRECTO.bat.'
    }
    $pythonWindow = Join-Path ([IO.Path]::GetDirectoryName($pythonPath)) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonWindow -PathType Leaf)) {
        throw 'No se encontro pythonw.exe junto a Python. Repara la instalacion de Python para poder abrir MarketIntel sin consola.'
    }

    # Resolves the user's actual Desktop, including OneDrive redirection.
    $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    if (-not $desktop -or -not (Test-Path -LiteralPath $desktop -PathType Container)) {
        throw 'No se encontro tu carpeta de Escritorio. Comprueba la configuracion de Windows u OneDrive.'
    }
    $shortcutPath = Join-Path $desktop 'MarketIntel.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonWindow
    $shortcut.Arguments = '"' + $launcherFile + '"'
    $shortcut.WorkingDirectory = $appDirectory
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Abrir MarketIntel e iniciar su servidor local'
    $icon = Join-Path $appDirectory 'static\marketintel.ico'
    if (Test-Path -LiteralPath $icon -PathType Leaf) {
        $shortcut.IconLocation = $icon + ',0'
    }
    $shortcut.Save()
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show(
        'Se creo MarketIntel en tu Escritorio. Abre ese icono: iniciara el servidor y la aplicacion. Conserva esta carpeta en su ubicacion; si la mueves, ejecuta de nuevo CREAR_ACCESO_DIRECTO.bat.',
        'MarketIntel', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    exit 0
} catch {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'MarketIntel', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch {
        Write-Host 'No se pudo crear el acceso directo. Comprueba Python y que la carpeta este completa.'
    }
    exit 1
}
