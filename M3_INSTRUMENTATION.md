# M3 ARM64 Segmentation Fault Instrumentation Guide

## Overview
This document describes the instrumentation added to help diagnose and prevent M3 segmentation faults caused by cross-thread Qt access.

## Quick Start

### Enable Thread Safety Checks at Startup
```python
from pychron.core.ui.gui import enable_thread_safety_checks

# Enable detailed thread safety monitoring
enable_thread_safety_checks(True)
```

### In Your Application's Initialization
```python
# pychron/applications/pychron.py or your main application file
def bootstrap(self):
    # ... existing code ...
    
    # Enable thread safety checks (especially useful on M3/ARM64)
    from pychron.core.ui.gui import enable_thread_safety_checks
    import sys
    
    # Check if running on M3
    is_m3 = 'arm64' in sys.platform.lower()
    enable_thread_safety_checks(is_m3)
```

## What Gets Instrumented

### 1. **invoke_in_main_thread() Function**
- Logs when operations are deferred to main thread
- Tracks source thread that queued the operation
- Warns if main thread is blocked >1s before executing

**Output in logs:**
```
[ThreadSafety] DEBUG: Deferred to main thread: _update_plot_panel_counts from WaitControl(id=123456789)
[ThreadSafety] DEBUG: Executing deferred: _update_plot_panel_counts
[EventLoopMonitor] WARNING: Event loop was blocked for 1.2s before executing _update_plot_panel_counts (was queued from WaitControl)
```

### 2. **PlotPanel Class**
- Monitors all trait assignments from `__setattr__`
- Detects cross-thread access to critical Qt traits:
  - `counts`, `total_counts`, `total_seconds`
  - `current_cycle`, `current_color`
  - `is_baseline`, `is_peak_hop`
  - `_ncounts`, `_ncycles`

**Output when detected:**
```
[ThreadSafety.PlotPanel] WARNING: ⚠️  CROSS-THREAD PLOT_PANEL ACCESS: Setting counts from data_collector. 
Use invoke_in_main_thread() to defer to main thread. This causes M3 ARM64 segfaults.
```

### 3. **Thread Safety Decorator**
Use on any function that does Qt operations:
```python
from pychron.core.ui.gui import qt_thread_safe

@qt_thread_safe("update plot panel counts")
def _update_plot_panel(self):
    self.plot_panel.counts = 5  # Will assert on M3 if called from worker thread
```

### 4. **assert_main_thread() Function**
Explicit check for main thread context:
```python
from pychron.core.ui.gui import assert_main_thread

def critical_qt_operation(self):
    assert_main_thread("critical Qt operation")
    # Safe to do Qt operations here
    self.plot_panel.counts = value
```

## Logging Levels and Output

### Thread Safety Logger
- **Logger Name**: `ThreadSafety`
- **Related Loggers**: `ThreadSafety.PlotPanel`, `EventLoopMonitor`

### What to Look For in Logs

**1. Normal Deferral (Good)**
```
[ThreadSafety] DEBUG: Deferred to main thread: _update_plot_panel_counts from data_collector
[ThreadSafety] DEBUG: Executing deferred: _update_plot_panel_counts
```

**2. Cross-Thread Access Detected (Warning)**
```
[ThreadSafety.PlotPanel] WARNING: ⚠️  CROSS-THREAD PLOT_PANEL ACCESS: Setting counts from data_collector
```

**3. Main Thread Blocked (Performance Issue)**
```
[EventLoopMonitor] WARNING: ⚠️  Event loop was blocked for 2.5s before executing _update_plot_panel_counts
```

**4. Exception in Deferred Operation**
```
[EventLoopMonitor] Exception in invoke_in_main_thread callback _update_plot_panel_counts
```

## Debugging M3 Crashes

### If You See a Crash with Pointer Authentication Error
1. Check logs for thread safety warnings
2. Look for `CROSS-THREAD PLOT_PANEL ACCESS` messages
3. Find the offending attribute assignment
4. Wrap it in `invoke_in_main_thread()`

### Example Crash Diagnostic
```
# Crash Log Snippet:
exception: EXC_BAD_ACCESS (SIGSEGV) "possible pointer authentication failure"
QCoreApplication::notifyInternal2 → QTimerInfoList::activateTimers()

# Corresponding Log Entry:
[ThreadSafety.PlotPanel] WARNING: ⚠️  CROSS-THREAD PLOT_PANEL ACCESS: Setting counts from data_collector
[ThreadSafety] DEBUG: Deferred to main thread: _update_plot_panel_counts from data_collector

# FIX: Check that the operation was actually wrapped in invoke_in_main_thread
```

## Performance Impact

- **Minimal overhead**: Thread checks are guards (~1-2μs per operation)
- **Can be disabled**: Set `enable_thread_safety_checks(False)` for production
- **Recommended**: Keep enabled on M3 development machines for early detection

## Testing on Different Platforms

### Local Development (M3)
```bash
# Enable full instrumentation
PYCHRON_THREAD_SAFETY=1 python -m pychron
```

### Continuous Integration
- Run with thread safety checks enabled on M3 CI nodes
- Check logs for any thread safety warnings
- File issues if warnings appear

### Regression Testing
```python
# In test suite
def test_measurement_thread_safety():
    """Verify no cross-thread Qt access during measurement"""
    from pychron.core.ui.gui import enable_thread_safety_checks
    enable_thread_safety_checks(True)
    
    # Run measurement that collects data
    # Should not trigger PlotPanel thread safety warnings
```

## Common Patterns to Fix

### Pattern 1: Direct Plot Panel Update in Collector
```python
# ❌ WRONG - causes M3 crash
class DataCollector:
    def _measure(self):
        while measuring:
            self.automated_run.plot_panel.counts = i

# ✅ RIGHT - safe
class DataCollector:
    def _measure(self):
        while measuring:
            invoke_in_main_thread(self._update_plot_panel_counts, i)
    
    def _update_plot_panel_counts(self, count):
        if self.automated_run and self.automated_run.plot_panel:
            self.automated_run.plot_panel.counts = count
```

### Pattern 2: Graph Operations in Measurement Script
```python
# ❌ WRONG - causes M3 crash
def py_measure(self):
    g = self.plot_panel.isotope_graph  # Worker thread!
    g.clear()

# ✅ RIGHT - safe
def py_measure(self):
    invoke_in_main_thread(self._setup_graph)

def _setup_graph(self):
    if self.plot_panel:
        g = self.plot_panel.isotope_graph
        g.clear()
```

### Pattern 3: Multiple Trait Updates
```python
# ❌ WRONG - multiple cross-thread accesses
self.plot_panel.is_baseline = True
self.plot_panel.show_baseline_graph()

# ✅ RIGHT - batched in one deferred call
invoke_in_main_thread(self._setup_baseline_on_main_thread)

def _setup_baseline_on_main_thread(self):
    if self.plot_panel:
        self.plot_panel.is_baseline = True
        self.plot_panel.show_baseline_graph()
```

## Future Work

- [ ] Auto-detection of cross-thread Qt access using AST analysis
- [ ] CI warnings for any cross-thread access patterns
- [ ] Performance profiling of defer overhead
- [ ] Automatic wrapping of suspected violations

## Questions?

Refer to the M3 ARM64 segfault fix documentation: `m3_arm64_segfault_fix.md`
