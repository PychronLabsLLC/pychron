# ===============================================================================
# Copyright 2026 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
"""
Crash Diagnostics for M3/ARM64 Segmentation Faults

Provides tools to analyze and diagnose segmentation faults caused by cross-thread
Qt access on Apple Silicon (M3) Macs with pointer authentication.

Usage:
    from pychron.core.ui.crash_diagnostics import analyze_crash_log

    # Analyze a crash report
    with open("crash.log") as f:
        analysis = analyze_crash_log(f.read())
        print(analysis.summary())
"""

import re
from typing import List
from dataclasses import dataclass


@dataclass
class CrashAnalysis:
    """Analysis results from a crash log."""

    is_m3_segfault: bool
    is_pointer_auth_failure: bool
    crash_in_qt_event_loop: bool
    suspected_cross_thread_access: bool
    stack_trace_lines: List[str]

    def summary(self) -> str:
        """Generate a summary of the crash analysis."""
        lines = ["=== M3 Crash Diagnostics ===\n"]

        if self.is_m3_segfault:
            lines.append("❌ M3/ARM64 Segmentation Fault Detected\n")

        if self.is_pointer_auth_failure:
            lines.append("⚠️  POINTER AUTHENTICATION FAILURE\n")
            lines.append(
                "   This occurs when invalid Qt objects are accessed from worker threads.\n"
            )
            lines.append(
                "   Solution: Wrap cross-thread Qt operations in invoke_in_main_thread()\n\n"
            )

        if self.crash_in_qt_event_loop:
            lines.append("📍 Crash Location: Qt Event Loop (QCoreApplication::notifyInternal2)\n")
            lines.append("   Likely cause: Qt timer or signal from worker thread\n\n")

        if self.suspected_cross_thread_access:
            lines.append("🔍 Suspected cross-thread access detected\n")
            lines.append(
                "   Check the following stack frames for plot_panel or graph operations\n\n"
            )

        if self.stack_trace_lines:
            lines.append("Stack Trace (Key Frames):\n")
            for line in self.stack_trace_lines[:10]:  # Show first 10 frames
                lines.append(f"  {line}\n")

        lines.append("\nReferenced Files:\n")
        lines.append("  - M3_INSTRUMENTATION.md - How to enable crash diagnostics\n")
        lines.append("  - m3_arm64_segfault_fix.md - Details of the fix\n")

        return "".join(lines)


def analyze_crash_log(log_content: str) -> CrashAnalysis:
    """Analyze a crash log for M3/ARM64 segmentation faults.

    Args:
        log_content: Contents of the crash log file

    Returns:
        CrashAnalysis with detection results
    """
    is_m3_segfault = False
    is_pointer_auth_failure = False
    crash_in_qt_event_loop = False
    suspected_cross_thread_access = False
    stack_trace_lines = []

    lines = log_content.split("\n")

    # Check for ARM64 and segfault indicators
    if "arm64" in log_content.lower() or "ARM-64" in log_content:
        is_m3_segfault = True

    if "segmentation fault" in log_content.lower() or "sigsegv" in log_content.lower():
        is_m3_segfault = True

    # Check for pointer authentication failure (key indicator)
    if "pointer authentication failure" in log_content.lower():
        is_pointer_auth_failure = True
        is_m3_segfault = True

    # Check for Qt event loop in crash context
    if "qcoreapplication" in log_content.lower() or "qtimerinfo" in log_content.lower():
        crash_in_qt_event_loop = True

    # Look for suspicious Qt operations
    suspicious_patterns = [
        r"plot_panel",
        r"isotope_graph",
        r"baseline_graph",
        r"\.counts",
        r"\.trait_set",
        r"\.counts\s*=",
        r"\.update\(\)",
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, log_content):
            suspected_cross_thread_access = True
            break

    # Extract stack trace
    in_stack = False
    for line in lines:
        if "thread" in line.lower() or "frame" in line.lower():
            in_stack = True
        elif in_stack and line.strip():
            # Look for function names in stack
            if any(x in line for x in ["(", ")", "0x", "+"]):
                stack_trace_lines.append(line.strip())
                if len(stack_trace_lines) >= 10:
                    break

    return CrashAnalysis(
        is_m3_segfault=is_m3_segfault,
        is_pointer_auth_failure=is_pointer_auth_failure,
        crash_in_qt_event_loop=crash_in_qt_event_loop,
        suspected_cross_thread_access=suspected_cross_thread_access,
        stack_trace_lines=stack_trace_lines,
    )


def suggest_fixes(analysis: CrashAnalysis) -> List[str]:
    """Suggest fixes based on crash analysis.

    Args:
        analysis: CrashAnalysis results

    Returns:
        List of suggested fixes
    """
    suggestions = []

    if analysis.is_pointer_auth_failure:
        suggestions.append(
            "1. Check for direct plot_panel/graph access from worker threads\n"
            "   Solution: Use invoke_in_main_thread() to defer to main thread"
        )
        suggestions.append(
            "2. Search for pattern: self.plot_panel.<attribute> = <value>\n"
            "   These should be wrapped in invoke_in_main_thread()"
        )
        suggestions.append(
            "3. Check data_collector.py and peak_hop_collector.py\n"
            "   These are common sources of cross-thread access"
        )

    if analysis.crash_in_qt_event_loop:
        suggestions.append(
            "4. The crash is in Qt's event loop\n"
            "   This indicates Qt state corruption from another thread"
        )

    if analysis.suspected_cross_thread_access:
        suggestions.append(
            "5. Suspected cross-thread Qt access detected in stack trace\n"
            "   Review the identified frames for plot_panel operations"
        )

    if not suggestions:
        suggestions.append(
            "Unable to identify specific cause.\n"
            "Check thread safety logs for CROSS-THREAD PLOT_PANEL ACCESS warnings."
        )

    return suggestions


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        crash_file = sys.argv[1]
        with open(crash_file) as f:
            content = f.read()

        analysis = analyze_crash_log(content)
        print(analysis.summary())
        print("\nSuggested Fixes:")
        for suggestion in suggest_fixes(analysis):
            print(suggestion)
    else:
        print("Usage: python crash_diagnostics.py <crash_log_file>")
