# Pre/Post hook tests (#550)

Paste a script into **Settings > Scripts**, give it a name, and save it. Select
it in wizard step 9, **Pre/Post scripts**, then save the job in step 10.
These examples only print markers and exit; they do not change files, containers,
VMs or remote servers. Use a disposable backup job for the integration tests.

| Script | Expected result |
| --- | --- |
| `pre-success.sh` | Pre returns 0; backup may start. |
| `pre-failure.sh` | Pre returns 41; no mounts, Docker/VM stops or backup. |
| `post-success.sh` | Post returns 0 after maintenance and cleanup. |
| `post-failure.sh` | Post returns 42; overall job fails, created archive remains visible. |
| `pre-syntax-error.sh` | Saving rejected: Bash syntax error at line 7. |
| `post-syntax-error.sh` | Saving rejected: Bash syntax error at line 7. |

The last two scripts are intentionally invalid; do not execute them. Their
missing `then` is reported at the closing `fi`. Saving runs `bash -n`, which
checks syntax without execution. The other four are syntactically valid and
exercise runtime exit codes instead.

Test combinations:

1. Pre success + Post success: verify both markers and successful completion.
2. Pre failure + Post success, **On success**: no backup and no Post marker.
3. Pre success + Post failure: history shows successful `borg create` and failed
   Post separately; final status and failure notification include the Post error.
4. Pre failure + Post failure, **Also on failure, skip or cancellation**: both
   failures appear; no backup starts.
5. Pre success + Post success with the same condition: cancel a test backup;
   Docker/VM recovery and share cleanup precede Post. The job remains cancelled.
6. Set a script to `sleep 5` with timeout 1: it times out and fails the job.
7. Start a job, edit its central Post script, then run again: the active run
   uses the old snapshot; the next run uses the edited definition.

Skipped runs caused by a resource-lock conflict have not started and execute
neither hook. A parity/USB skip after Pre follows the selected Post condition.

## Practical templates (#557)

For configurable source checks, Wake-on-LAN, database dumps and a Post webhook,
see the separate [practical collection](practical/README.md)
([Deutsch](practical/README.de.md)). Unlike the smoke-test scripts above, those
templates can write exports or contact services after explicit configuration.
