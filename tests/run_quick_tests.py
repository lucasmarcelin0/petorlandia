"""
Quick Test Execution Script

Run this to quickly verify all critical functionality.
"""
import subprocess
import sys


def run_quick_tests():
    """Run a quick subset of critical tests."""
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║         PETORLANDIA QUICK TEST VERIFICATION                ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    critical_tests = [
        ("Authentication & Security", "tests/test_security_authorization.py::TestAuthentication"),
        ("Tutor Registration", "tests/test_e2e_tutor_workflows.py::TestTutorRegistrationAndLogin"),
        ("Animal Management", "tests/test_e2e_tutor_workflows.py::TestAnimalManagement::test_add_animal_complete_flow"),
        ("Consultation Flow", "tests/test_e2e_veterinarian_workflows.py::TestConsultationWorkflow::test_create_consultation"),
        ("Data Isolation", "tests/test_security_authorization.py::TestDataIsolation"),
        ("Form Accessibility", "tests/test_accessibility_ui.py::TestFormAccessibility"),
    ]
    
    failed = []
    passed = []
    
    for name, test_path in critical_tests:
        print(f"\n▶ Testing: {name}")
        try:
            result = subprocess.run(
                ['pytest', test_path, '-v', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                print(f"  ✓ PASSED")
                passed.append(name)
            else:
                print(f"  ✗ FAILED")
                failed.append(name)
                if '--verbose' in sys.argv:
                    print(result.stdout)
        
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            failed.append(name)
    
    print(f"\n{'='*60}")
    print(f"QUICK TEST RESULTS")
    print(f"{'='*60}")
    print(f"Passed: {len(passed)}/{len(critical_tests)}")
    print(f"Failed: {len(failed)}/{len(critical_tests)}")
    
    if failed:
        print(f"\nFailed tests:")
        for test in failed:
            print(f"  - {test}")
        print(f"\nRun with --verbose flag for details")
        print(f"Or run: pytest tests/ -v")
        return 1
    else:
        print(f"\n🎉 All critical tests passed!")
        print(f"\nTo run complete test suite:")
        print(f"  python tests/run_all_tests.py")
        return 0


if __name__ == '__main__':
    sys.exit(run_quick_tests())
