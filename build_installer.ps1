param(
    [string]$Version = ""
)

# Build Tool Muse Windows Installer with Auto Version Bumping
$ErrorActionPreference = "Stop"
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "            TOOL MUSE - DONG GOI FILE CAI DAT (INSTALLER)" -ForegroundColor Cyan
Write-Host "=====================================================================`n" -ForegroundColor Cyan

Set-Location $PSScriptRoot

# 1. Version Bumping
$versionFile = Join-Path $PSScriptRoot "VERSION"
$currentVersion = "1.0.0"
if (Test-Path $versionFile) {
    $currentVersion = (Get-Content $versionFile -Raw).Trim()
}

if ($Version -and $Version.Trim()) {
    $newVersion = $Version.Trim().TrimStart('v')
} else {
    if ($currentVersion -match '^(.*?)(\d+)\.(\d+)\.(\d+)$') {
        $prefix = $matches[1]
        $major = [int]$matches[2]
        $minor = [int]$matches[3]
        $patch = [int]$matches[4] + 1
        $newVersion = "$prefix$major.$minor.$patch"
    } elseif ($currentVersion -match '^(\d+)\.(\d+)\.(\d+)$') {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        $patch = [int]$matches[3] + 1
        $newVersion = "$major.$minor.$patch"
    } else {
        $newVersion = "1.0.1"
    }
}

[System.IO.File]::WriteAllText($versionFile, $newVersion, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ">>> Phien ban moi (New Version): v$newVersion (ban truoc: v$currentVersion)`n" -ForegroundColor Green

# Cap nhat phien ban vao cac file he thong:
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Safe-WriteText($path, $content, $encoding) {
    for ($i = 0; $i -lt 5; $i++) {
        try {
            [System.IO.File]::WriteAllText($path, $content, $encoding)
            return
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    try {
        Set-Content -Path $path -Value $content -Encoding UTF8 -NoNewline
    } catch {
        $tempPath = "$path.tmp"
        [System.IO.File]::WriteAllText($tempPath, $content, $encoding)
        Move-Item -Path $tempPath -Destination $path -Force
    }
}

# 1.1 installer.iss
if (Test-Path "installer.iss") {
    $issContent = [System.IO.File]::ReadAllText("installer.iss", [System.Text.Encoding]::UTF8)
    $issContent = [regex]::Replace($issContent, '(#define\s+MyAppVersion\s+)"[^"]*"', "`${1}`"$newVersion`"")
    Safe-WriteText "installer.iss" $issContent $utf8NoBom
}

# 1.2 desktop.py
if (Test-Path "desktop.py") {
    $desktopContent = [System.IO.File]::ReadAllText("desktop.py", [System.Text.Encoding]::UTF8)
    $desktopContent = [regex]::Replace($desktopContent, '(?s)(def get_version\(.*?return\s+)"[^"]*"', "`${1}`"$newVersion`"")
    Safe-WriteText "desktop.py" $desktopContent $utf8NoBom
}

# 2. Check tools
Write-Host "[1/4] Kiem tra cong cu bien dich..." -ForegroundColor Yellow
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Dang cai dat PyInstaller..."
    pip install pyinstaller pillow
}

$iscc = "C:\Users\vuive\AppData\Local\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe"
if (-not (Test-Path $iscc)) {
    $iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $iscc)) {
    $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $iscc)) {
    $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $iscc)) {
    throw "Khong tim thay Inno Setup 6 (ISCC.exe)! Vui long cai dat tu https://jrsoftware.org/isdl.php"
}

# 3. Check icon & Python redist installer
Write-Host "[2/4] Kiem tra icon ung dung va bo cai Python offline..." -ForegroundColor Yellow
if (-not (Test-Path "app_icon.ico")) {
    python -c "from PIL import Image, ImageDraw; img = Image.new('RGBA', (256, 256), (0,0,0,0)); draw = ImageDraw.Draw(img); draw.rounded_rectangle([16, 16, 240, 240], radius=52, fill=(100, 40, 210, 255)); img.save('app_icon.ico', format='ICO')"
}

$redistDir = Join-Path $PSScriptRoot "redist"
$redistPy = Join-Path $redistDir "python-3.12.10-amd64.exe"
if (-not (Test-Path $redistPy)) {
    New-Item -ItemType Directory -Force -Path $redistDir | Out-Null
    Write-Host "Dang tai bo cai Python 3.12 64-bit offline ve thu muc redist..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $redistPy
}

# 4. Compile ToolMuse.exe
Write-Host "[3/4] Don dep va bien dich trinh khoi chay ToolMuse.exe..." -ForegroundColor Yellow
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
if (-not (Test-Path "dist_installer")) { New-Item -ItemType Directory -Force -Path "dist_installer" | Out-Null }
pyinstaller --onefile --noconsole --icon=app_icon.ico --name="ToolMuse" --noconfirm launcher.py

# 5. Compile Inno Setup Installer
Write-Host "[4/4] Bien dich Windows Installer (.exe) phien ban $newVersion..." -ForegroundColor Yellow
& $iscc "/DMyAppVersion=$newVersion" installer.iss

$outputExe = "dist_installer\Tool_Muse_Setup_$newVersion.exe"
Write-Host "`n=====================================================================" -ForegroundColor Green
Write-Host " THANH CONG! File cai dat moi da san sang tai:" -ForegroundColor Green
Write-Host " $outputExe" -ForegroundColor Green
Write-Host "=====================================================================`n" -ForegroundColor Green
