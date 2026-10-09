#!/bin/bash
# Issue #550: PRE hook test. No arguments or environment variables required.
# Writes a phase marker to stdout; intentional failures also write to stderr.
# Returns 41; does not change files, services, containers, or remote systems.
printf '%s\n' '[BBUI TEST PRE] Started.'
printf '%s\n' '[BBUI TEST PRE] Intentional test failure (exit 41).' >&2
exit 41
