[CmdletBinding()]
param(
    [string]$TestPath = "",
    [string[]]$PytestArgs = @(),
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
$repository = Split-Path -Parent $PSScriptRoot

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & git -c "safe.directory=$repository" -C $repository @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git falhou: git $($Arguments -join ' ')"
    }
}

Push-Location $repository
try {
    $herokuUrl = (& git -c "safe.directory=$repository" -C $repository remote get-url heroku 2>$null)
    if ($LASTEXITCODE -ne 0 -or $herokuUrl -notmatch '^https://git\.heroku\.com/.+\.git/?$') {
        throw "O remoto 'heroku' nao existe ou nao aponta para o Git do Heroku."
    }

    $trackedChanges = @(& git -c "safe.directory=$repository" -C $repository status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel verificar o estado do repositorio."
    }
    if ($trackedChanges.Count -gt 0) {
        throw "Ha alteracoes rastreadas sem commit. Revise e crie o commit antes do deploy."
    }

    Write-Host "Atualizando a referencia heroku/main..." -ForegroundColor Cyan
    Invoke-Git fetch heroku main

    $headCommit = (& git -c "safe.directory=$repository" -C $repository rev-parse HEAD).Trim()
    $remoteCommit = (& git -c "safe.directory=$repository" -C $repository rev-parse heroku/main).Trim()
    & git -c "safe.directory=$repository" -C $repository merge-base --is-ancestor $remoteCommit $headCommit
    if ($LASTEXITCODE -ne 0) {
        throw @"
O Heroku possui commits que nao estao no commit atual.
Integre heroku/main em uma branch de deploy e resolva os conflitos antes de tentar novamente.
Nao use --force: isso pode apagar correcoes que ja estao em producao.
"@
    }

    if ($TestPath) {
        $pythonCandidates = @(
            (Join-Path $repository ".venv\Scripts\python.exe"),
            (Join-Path $repository ".venv-codex\Scripts\python.exe")
        )
        $python = $null
        foreach ($candidate in $pythonCandidates) {
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            try {
                & $candidate --version *> $null
            } catch {
                continue
            }
            if ($LASTEXITCODE -eq 0) {
                $python = $candidate
                break
            }
        }
        if (-not $python) {
            throw @"
Nenhum ambiente Python funcional foi encontrado.
Os ambientes .venv foram criados com uma instalacao antiga da Microsoft Store.
Reinstale o Python 3.12 e recrie o ambiente com: py -3.12 -m venv .venv
Depois execute: .\.venv\Scripts\python.exe -m pip install -r requirements.txt
"@
        }

        Write-Host "Executando testes antes do deploy..." -ForegroundColor Cyan
        & $python -m pytest $TestPath @PytestArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Os testes falharam; o deploy foi cancelado."
        }
    } else {
        Write-Host "Testes nao solicitados. Use -TestPath <arquivo-ou-diretorio> para executa-los." -ForegroundColor Yellow
    }

    if ($PreflightOnly) {
        Write-Host "Preflight concluido; nenhum deploy foi realizado." -ForegroundColor Green
        return
    }

    Write-Host "Publicando $headCommit no Heroku..." -ForegroundColor Cyan
    Invoke-Git push heroku HEAD:main

    $publishedCommit = ""
    foreach ($attempt in 1..5) {
        $publishedLine = (& git -c "safe.directory=$repository" -C $repository ls-remote heroku refs/heads/main 2>$null)
        if ($LASTEXITCODE -eq 0 -and $publishedLine) {
            $publishedCommit = ($publishedLine -split '\s+')[0]
            if ($publishedCommit -eq $headCommit) { break }
        }
        Start-Sleep -Seconds 3
    }
    if ($publishedCommit -ne $headCommit) {
        throw "O push terminou, mas o Heroku ainda nao confirma o commit $headCommit."
    }

    Write-Host "Deploy confirmado no Heroku: $headCommit" -ForegroundColor Green
} finally {
    Pop-Location
}
