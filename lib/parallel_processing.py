#!/usr/bin/env python3
"""
lib/parallel_processing.py
Real Parallel Processing (Layer 25).
"""
import concurrent.futures


def run_independent_tasks(tasks):
    results = {}
    errors = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks) or 1) as executor:
        future_to_name = {
            executor.submit(fn, *args): name
            for name, (fn, args) in tasks.items()
        }
        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                errors[name] = str(e)

    return {"results": results, "errors": errors}
