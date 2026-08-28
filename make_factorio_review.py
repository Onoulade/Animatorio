#!/usr/bin/env python3
"""Deprecated shim — use make_validation_review.py instead."""
import warnings
warnings.warn("make_factorio_review.py is deprecated; use make_validation_review.py", DeprecationWarning)
import make_validation_review as _m
if __name__ == "__main__":
    _m.main()
