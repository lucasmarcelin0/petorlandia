# Fix Encoding Issues in Test Files
# This script replaces Portuguese special characters with ASCII equivalents

Write-Host "`n🔧 Fixing encoding issues in test files...`n" -ForegroundColor Cyan

$testFiles = @(
    "test_e2e_tutor_workflows.py",
    "test_e2e_veterinarian_workflows.py",
    "test_security_authorization.py",
    "test_accessibility_ui.py"
)

$replacements = @{
    'Veterinária' = 'Veterinaria'
    'fêmea' = 'femea'
    'João' = 'Joao'
    'orçamento' = 'orcamento'
    'ê' = 'e'
    'á' = 'a'
    'é' = 'e'
    'í' = 'i'
    'ó' = 'o'
    'ú' = 'u'
    'â' = 'a'
    'ã' = 'a'
    'õ' = 'o'
    'ç' = 'c'
    'Ç' = 'C'
}

$fixed = 0
$errors = 0

foreach ($file in $testFiles) {
    $filePath = Join-Path $PSScriptRoot $file
    
    if (Test-Path $filePath) {
        try {
            Write-Host "  Processing: $file" -ForegroundColor Yellow
            
            # Read with UTF-8 encoding
            $content = [System.IO.File]::ReadAllText($filePath, [System.Text.Encoding]::UTF8)
            
            # Apply replacements
            foreach ($key in $replacements.Keys) {
                $content = $content.Replace($key, $replacements[$key])
            }
            
            # Write with ASCII encoding
            [System.IO.File]::WriteAllText($filePath, $content, [System.Text.Encoding]::ASCII)
            
            Write-Host "    ✓ Fixed: $file" -ForegroundColor Green
            $fixed++
        }
        catch {
            Write-Host "    ✗ Error: $_" -ForegroundColor Red
            $errors++
        }
    }
    else {
        Write-Host "    ⚠ Not found: $file" -ForegroundColor DarkYellow
    }
}

Write-Host "`n📊 Summary:" -ForegroundColor Cyan
Write-Host "  Fixed: $fixed files" -ForegroundColor Green
Write-Host "  Errors: $errors files" -ForegroundColor $(if ($errors -gt 0) { "Red" } else { "Green" })

if ($fixed -gt 0) {
    Write-Host "`n✨ Encoding issues fixed! Now run:" -ForegroundColor Green
    Write-Host "  pytest tests/ --collect-only -q" -ForegroundColor White
    Write-Host "  pytest tests/test_e2e_tutor_workflows.py -v`n" -ForegroundColor White
}
