"""
Test Runner and Reporting Script

This script runs the comprehensive test suite and generates detailed reports.
"""
import subprocess
import sys
import os
from datetime import datetime
import json


class TestRunner:
    """Manages test execution and reporting."""
    
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'suites': []
        }
    
    def run_test_suite(self, name, test_path, markers=None):
        """Run a specific test suite and capture results."""
        print(f"\n{'='*60}")
        print(f"Running: {name}")
        print(f"{'='*60}\n")
        
        cmd = ['pytest', test_path, '-v', '--tb=short']
        
        if markers:
            cmd.extend(['-m', markers])
        
        # Add coverage if available
        cmd.extend(['--cov=.', '--cov-report=term-missing', '--cov-append'])
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            suite_result = {
                'name': name,
                'path': test_path,
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'passed': result.returncode == 0
            }
            
            self.results['suites'].append(suite_result)
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            return result.returncode == 0
            
        except subprocess.TimeoutExpired:
            print(f"ERROR: {name} tests timed out after 300 seconds")
            return False
        except Exception as e:
            print(f"ERROR running {name}: {e}")
            return False
    
    def generate_report(self, output_file='test_report.json'):
        """Generate JSON report of test results."""
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        print(f"\nTest report saved to {output_file}")
    
    def print_summary(self):
        """Print summary of all test results."""
        print(f"\n{'='*60}")
        print("TEST EXECUTION SUMMARY")
        print(f"{'='*60}\n")
        
        total_suites = len(self.results['suites'])
        passed_suites = sum(1 for s in self.results['suites'] if s['passed'])
        failed_suites = total_suites - passed_suites
        
        print(f"Total Test Suites: {total_suites}")
        print(f"Passed:           {passed_suites} ✓")
        print(f"Failed:           {failed_suites} ✗")
        print(f"\nExecution Time:   {self.results['timestamp']}")
        
        if failed_suites > 0:
            print("\nFailed Suites:")
            for suite in self.results['suites']:
                if not suite['passed']:
                    print(f"  - {suite['name']}")
        
        print(f"\n{'='*60}\n")
        
        return failed_suites == 0


def main():
    """Main test execution function."""
    runner = TestRunner()
    
    # Define test suites
    test_suites = [
        # Existing comprehensive tests
        {
            'name': 'Core Routes and Features',
            'path': 'tests/test_routes.py'
        },
        
        # New comprehensive E2E tests
        {
            'name': 'Tutor Workflows E2E',
            'path': 'tests/test_e2e_tutor_workflows.py'
        },
        {
            'name': 'Veterinarian Workflows E2E',
            'path': 'tests/test_e2e_veterinarian_workflows.py'
        },
        
        # Security tests
        {
            'name': 'Security and Authorization',
            'path': 'tests/test_security_authorization.py'
        },
        
        # Accessibility tests
        {
            'name': 'Accessibility and UI',
            'path': 'tests/test_accessibility_ui.py'
        },
        
        # Existing specialized tests
        {
            'name': 'Appointment Management',
            'path': 'tests/test_agendamentos.py'
        },
        {
            'name': 'Clinic Management',
            'path': 'tests/test_minha_clinica.py'
        },
        {
            'name': 'Financial Operations',
            'path': 'tests/test_accounting_links.py'
        },
        {
            'name': 'Data Isolation',
            'path': 'tests/test_clinic_access.py'
        },
        {
            'name': 'Prescription Management',
            'path': 'tests/test_imprimir_bloco_prescricao.py'
        }
    ]
    
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║         PETORLANDIA COMPREHENSIVE TEST SUITE               ║
    ║                                                            ║
    ║  Testing all features for reliability and performance     ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    all_passed = True
    
    for suite in test_suites:
        passed = runner.run_test_suite(suite['name'], suite['path'])
        if not passed:
            all_passed = False
    
    # Generate reports
    runner.generate_report()
    success = runner.print_summary()
    
    if success:
        print("🎉 All tests passed! Application is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please review the failures above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
