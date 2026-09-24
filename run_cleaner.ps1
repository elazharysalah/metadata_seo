# Resolves the real Python used by "py -3" and starts the GUI from this folder.
# Double-click run_cleaner.bat to run (avoids ExecutionPolicy issues on .ps1).

$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location -LiteralPath $here
$gui = Join-Path $here 'metadata_cleaner_gui.py'

if (-not (Test-Path -LiteralPath $gui)) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        "Cannot find metadata_cleaner_gui.py in:`n$here",
        'Metadata Cleaner',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

function Get-PythonExe {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $line = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $line) {
            $p = ($line | Select-Object -First 1).ToString().Trim()
            if ($p -and (Test-Path -LiteralPath $p)) { return $p }
        }
    }

    foreach ($name in @('python', 'python3')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $c) { continue }
        if ($c.Source -match 'WindowsApps') { continue }
        if (Test-Path -LiteralPath $c.Source) { return $c.Source }
    }

    foreach ($root in @('HKLM:\SOFTWARE\Python\PythonCore', 'HKCU:\SOFTWARE\Python\PythonCore')) {
        if (-not (Test-Path $root)) { continue }
        foreach ($item in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
            $ip = (Get-ItemProperty -Path (Join-Path $item.PSPath 'InstallPath') -ErrorAction SilentlyContinue).'(default)'
            if ($ip) {
                $e = Join-Path $ip 'python.exe'
                if (Test-Path -LiteralPath $e) { return $e }
            }
        }
    }

    return $null
}

$python = Get-PythonExe
if (-not $python) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        "Could not find Python (same as when you type py -3).`n`nInstall from https://www.python.org/downloads/ and enable Add to PATH,`nor repair the Python Launcher.",
        'Metadata Cleaner',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

$p = Start-Process -FilePath $python -ArgumentList @("`"$gui`"") -WorkingDirectory $here -PassThru -Wait
$code = 0
if ($p -and $p.ExitCode -ne $null) { $code = $p.ExitCode }
exit $code
