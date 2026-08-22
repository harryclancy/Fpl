# Pre-deadline snapshots

One file per gameweek, holding the squad this app recommended *before*
that gameweek's deadline.

They're committed rather than written only at runtime because the app is
deployed on a host with an ephemeral filesystem — a runtime-only snapshot
disappears on the next container restart, which is usually before you'd
want to look at it. The workflow in `.github/workflows/snapshot.yml`
writes and commits them automatically ahead of each deadline; the app also
writes one at runtime as a fallback.

Nothing here is written after a gameweek kicks off. That's the whole
point: recomputing a gameweek's advice once results are in produces a
squad nobody could have picked at the only moment it could have been used.
