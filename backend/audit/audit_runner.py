#!/usr/bin/env python3
"""Inline audit runner - executes council_audit.py logic directly."""
import sys
import os

# Add backend to path
backend_path = "/mnt/c/Users/USER/Downloads/b_a6LznsoAKUT-1774336963705/backend"
sys.path.insert(0, backend_path)
os.chdir(backend_path)

# Import and run the audit
from council_audit import audit_codebase

if __name__ == "__main__":
    audit_codebase()
