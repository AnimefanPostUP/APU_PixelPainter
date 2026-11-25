# Build the Pixel Painter native backend (C# -> NativeAOT native library).
#
#   powershell -ExecutionPolicy Bypass -File native/build.ps1            # this machine's platform
#   powershell -ExecutionPolicy Bypass -File native/build.ps1 -Rid win-x64
#
# Requirements: .NET 10 SDK (or newer) and the platform's native toolchain
# (Windows: Visual Studio / Build Tools with "Desktop development with C++").
# NativeAOT cannot cross-compile between operating systems: build the Linux /
# macOS libraries on those systems (pwsh works there too).
#
# The library is copied to native/runtimes/<rid>/, where utils/native.py looks
# for it. Blender keeps a loaded library open: restart Blender to pick up a
# rebuilt one.

param(
    [string]$Rid = "",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root "PixelPainterNative/PixelPainterNative.csproj"

if (-not $Rid) {
    $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLower()
    if ($IsLinux) { $Rid = "linux-$arch" }
    elseif ($IsMacOS) { $Rid = "osx-$arch" }
    else { $Rid = "win-$arch" }
}

if ($Rid.StartsWith("win") -and -not (Get-Command vswhere.exe -ErrorAction SilentlyContinue)) {
    # NativeAOT locates the MSVC linker through vswhere.exe, which usually isn't on PATH.
    $installer = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer"
    if (Test-Path (Join-Path $installer "vswhere.exe")) { $env:PATH = "$installer;$env:PATH" }
}

$publishDir = Join-Path $root "PixelPainterNative/obj/publish/$Rid"
$outDir = Join-Path $root "runtimes/$Rid"

Write-Host "Building PixelPainterNative for $Rid ($Configuration)..."
dotnet publish $project -c $Configuration -r $Rid -o $publishDir --nologo
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed ($LASTEXITCODE)" }

if ($Rid.StartsWith("win")) { $lib = "PixelPainterNative.dll" }
elseif ($Rid.StartsWith("osx")) { $lib = "PixelPainterNative.dylib" }
else { $lib = "PixelPainterNative.so" }

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Copy-Item (Join-Path $publishDir $lib) (Join-Path $outDir $lib) -Force
Write-Host "-> $(Join-Path $outDir $lib)"
