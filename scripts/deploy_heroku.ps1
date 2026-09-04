<#
.SYNOPSIS
Publica no Heroku depois de checar o que costuma quebrar o release phase.

.DESCRIPTION
Ordem: checagens de repositorio -> preflight de migrations -> testes (se
pedidos) -> push. Qualquer etapa que falhe cancela o deploy.

O preflight (scripts/preflight_deploy.py) roda sempre, porque a falha mais
comum -- duas cabecas do Alembic -- nao depende de ter mudado codigo: ela
aparece sozinha quando duas branches criam migration em paralelo, e derruba o
"release: flask db upgrade" do Procfile.

.EXAMPLE
.\scripts\deploy_heroku.ps1
Publica rodando as checagens.

.EXAMPLE
.\scripts\deploy_heroku.ps1 -PreflightOnly
So checa; nao publica.

.EXAMPLE
.\scripts\deploy_heroku.ps1 -TestPath tests\test_vacina_pmo_service.py
Publica rodando tambem esses testes.
#>
[CmdletBinding()]
param(
    [string]$TestPath = "",
    [string[]]$PytestArgs = @(),
    [switch]$PreflightOnly,
    [switch]$SkipPreflight
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

function Resolve-Python {
    # Os ambientes .venv deste repositorio foram criados com uma instalacao
    # antiga da Microsoft Store que nao executa mais; por isso cada candidato e
    # testado de verdade antes de ser escolhido.
    $candidates = @(
        (Join-Path $repository ".venv\Scripts\python.exe"),
        (Join-Path $repository ".venv-codex\Scripts\python.exe"),
        (Join-Path (Split-Path -Parent $repository) "venv\Scripts\python.exe"),
        ((Get-Command python -ErrorAction SilentlyContinue).Source)
    )
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            & $candidate --version *> $null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    throw @"
Nenhum ambiente Python funcional foi encontrado.
Recrie o ambiente com: py -3.12 -m venv .venv
Depois execute: .\.venv\Scripts\python.exe -m pip install -r requirements.txt
"@
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

    $python = Resolve-Python

    if (-not $SkipPreflight) {
        Write-Host "Checando o que o release phase vai executar..." -ForegroundColor Cyan
        & $python (Join-Path $repository "scripts\preflight_deploy.py")
        if ($LASTEXITCODE -ne 0) {
            throw "O preflight reprovou; o deploy foi cancelado. Corrija os itens acima."
        }
    } else {
        Write-Host "Preflight pulado por -SkipPreflight." -ForegroundColor Yellow
    }

    if ($TestPath) {
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
