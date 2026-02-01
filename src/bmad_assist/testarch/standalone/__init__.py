"""TEA Standalone Runner module.

This module provides standalone execution capability for TEA workflows
without requiring a full development loop or state.yaml persistence.

Designed for TEA Solo/Lite engagement models where users want quick
test setup or code analysis without full project initialization.

Usage:
    from bmad_assist.testarch.standalone import StandaloneRunner

    runner = StandaloneRunner(Path("."))
    result = runner.run_framework()
    print(result["output_path"])

CLI:
    bmad-assist tea framework    # Initialize test framework
    bmad-assist tea ci           # Create CI pipeline config
    bmad-assist tea test-design  # Generate test design docs
    bmad-assist tea automate     # Generate test automation
    bmad-assist tea nfr-assess   # Assess non-functional requirements

Story 25.13: TEA Standalone Runner & CLI.
"""

from bmad_assist.testarch.standalone.runner import StandaloneRunner

__all__ = [
    "StandaloneRunner",
]
