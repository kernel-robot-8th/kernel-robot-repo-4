# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Windows helper for the team Docker dev environment.
#
# This script does NOT run Docker and does NOT change any setting.
# It checks WSL, Docker Desktop and where the repository is, then prints
# the next commands to type in the Ubuntu (WSL) terminal.
# All real work is done by scripts/docker/dev.sh inside WSL.
# Why one script only: docs/dev_docker_guide.md section 2.2.
#
# Run (no system setting is changed; the bypass is for this one process):
#   powershell -ExecutionPolicy Bypass -File scripts\docker\dev.ps1 test
#
# This file is ASCII only on purpose. Windows PowerShell 5.1 reads a file
# without a BOM in the system code page, so Korean text could break parsing.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$guide = 'docs/dev_docker_guide.md'
$devArgs = @($args)
$wantsHelp = ($devArgs.Count -eq 0) -or ($devArgs[0] -in @('help', '-h', '--help'))
if ($devArgs.Count -eq 0) {
    $argText = 'help'
} else {
    $argText = $devArgs -join ' '
}

function Write-Line([string] $text) {
    Write-Host "[dev.ps1] $text"
}

Write-Line 'This script runs nothing. Use dev.sh inside WSL (Ubuntu).'
Write-Line "Guide: $guide (section 2.2 Windows)"
Write-Host ''

# 1) WSL
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($null -ne $wsl) {
    Write-Line 'WSL ............ found'
} else {
    Write-Line 'WSL ............ NOT FOUND'
    Write-Line '  -> In an administrator PowerShell: wsl --install -d Ubuntu-24.04'
    Write-Line '  -> Reboot, then open "Ubuntu 24.04" from the Start menu.'
    Write-Line '  -> Error 0x80370102 means CPU virtualization is off. Guide section 5.'
}

# 2) Docker Desktop (only checks that the process is running)
$desktop = Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue
if ($null -ne $desktop) {
    Write-Line 'Docker Desktop . running'
} else {
    Write-Line 'Docker Desktop . not running (or not installed)'
    Write-Line '  -> Install / start Docker Desktop.'
    Write-Line '  -> Settings > Resources > WSL integration > turn on Ubuntu-24.04.'
    Write-Line '  -> If WSL or Docker Desktop does not start, check that CPU virtualization'
    Write-Line '     is enabled (Task Manager > Performance > CPU). Guide section 5.'
}

# 3) Repository location
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
$wslPattern = '^\\\\wsl(\.localhost|\$)\\([^\\]+)\\(.*)$'
Write-Host ''
if ($repoRoot -match $wslPattern) {
    $distro = $Matches[2]
    $linuxPath = '/' + ($Matches[3] -replace '\\', '/')
    Write-Line "Repository ..... inside WSL ($distro): $linuxPath"
    Write-Host ''
    Write-Line "Next: open the '$distro' terminal and type:"
    Write-Host "    cd '$linuxPath'"
    Write-Host "    bash scripts/docker/dev.sh $argText"
} else {
    Write-Line "Repository ..... on a Windows drive: $repoRoot"
    Write-Line '  Do not build here: CRLF line endings break shell scripts,'
    Write-Line '  and file sharing from a Windows drive to Docker is slow.'
    Write-Host ''
    Write-Line 'Next: clone the repository again inside WSL. In the Ubuntu terminal:'
    Write-Host '    git config --global core.autocrlf input'
    Write-Host '    cd ~'
    Write-Host '    git clone <repository URL> <ws>'
    Write-Host '    cd <ws>'
    Write-Host '    bash scripts/docker/dev.sh build-image'
    Write-Host "    bash scripts/docker/dev.sh $argText"
}

if ($wantsHelp) {
    exit 0
}
Write-Host ''
Write-Line "Nothing was run for '$argText'. Run the command above inside WSL."
exit 1
