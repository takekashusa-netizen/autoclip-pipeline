#!/usr/bin/env python3
"""
lib/failure_recovery.py
Real Failure Recovery interface (Layer 46).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import doctor


def get_recovery_status():
    return {
        "any_job_needs_resuming": doctor.any_job_needs_resuming(),
        "duplicate_processes_found": bool(doctor.check_duplicate_processes()),
        "stale_locks_found": bool(doctor.check_stale_locks()),
        "disk_space_ok": doctor.check_disk_space(),
        "stalled_progress_jobs": doctor.check_stalled_progress(),
    }


def trigger_recovery(auto_approve=True):
    return doctor.auto_resume(auto_approve=auto_approve)
