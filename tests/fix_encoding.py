#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fix Encoding Issues in Test Files

This script replaces Portuguese special characters with ASCII equivalents.
"""
import os
import sys

def fix_encoding(filepath):
    """Fix encoding issues in a file."""
    replacements = {
        'Veterinária': 'Veterinaria',
        'fêmea': 'femea',
        'João': 'Joao',
        'orçamento': 'orcamento',
        'ê': 'e',
        'á': 'a',
        'é': 'e',
        'í': 'i',
        'ó': 'o',
        'ú': 'u',
        'â': 'a',
        'ã': 'a',
        'õ': 'o',
        'ç': 'c',
        'Ç': 'C',
    }
    
    try:
        # Read file
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Apply replacements
        for old, new in replacements.items():
            content = content.replace(old, new)
        
        # Write back as ASCII
        with open(filepath, 'w', encoding='ascii', errors='replace') as f:
            f.write(content)
        
        print(f"  ✓ Fixed: {os.path.basename(filepath)}")
        return True
        
    except Exception as e:
        print(f"  ✗ Error fixing {os.path.basename(filepath)}: {e}")
        return False


def main():
    print("\n🔧 Fixing encoding issues in test files...\n")
    
    test_files = [
        'test_e2e_tutor_workflows.py',
        'test_e2e_veterinarian_workflows.py',
        'test_security_authorization.py',
        'test_accessibility_ui.py',
    ]
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fixed = 0
    errors = 0
    
    for filename in test_files:
        filepath = os.path.join(script_dir, filename)
        
        if os.path.exists(filepath):
            print(f"  Processing: {filename}")
            if fix_encoding(filepath):
                fixed += 1
            else:
                errors += 1
        else:
            print(f"  ⚠ Not found: {filename}")
    
    print(f"\n📊 Summary:")
    print(f"  Fixed: {fixed} files")
    print(f"  Errors: {errors} files")
    
    if fixed > 0:
        print(f"\n✨ Encoding issues fixed! Now run:")
        print(f"  pytest tests/ --collect-only -q")
        print(f"  pytest tests/test_e2e_tutor_workflows.py -v\n")
    
    return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
