#!/bin/bash
# Issue #550: intentionally invalid PRE hook for save-time syntax validation.
# No arguments needed. Do not execute; validate with bash -n.
# Missing 'then': Bash reports the syntax error at 'fi' on line 7.
if true
    printf '%s\n' '[BBUI TEST PRE] This script must be rejected.'
fi
