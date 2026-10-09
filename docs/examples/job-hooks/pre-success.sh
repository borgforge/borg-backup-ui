#!/bin/bash
# Issue #550: PRE hook test. No arguments or environment variables required.
# Writes a phase marker to stdout; intentional failures also write to stderr.
# Returns 0; does not change files, services, containers, or remote systems.
printf '%s\n' '[BBUI TEST PRE] Started.'
printf '%s\n' '[BBUI TEST PRE] Completed successfully.'
exit 0
