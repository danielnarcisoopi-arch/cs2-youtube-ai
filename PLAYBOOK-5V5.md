# CS2 Playbook 5v5 Shorts

This is a separate daily video series and GitHub Actions workflow. It does not
change the existing Skin Market or Round IQ workflow.

## Run a preview

1. Open **Actions → CS2 Playbook 5v5 Shorts → Run workflow**.
2. Leave **Upload this manually started test to YouTube** unchecked.
3. Download the `cs2-playbook-*` artifact when the run finishes.

## Publishing

The workflow runs daily at 18:30 UTC (19:30 in Lisbon during summer time) and
uploads automatically using the existing `YOUTUBE_TOKEN_JSON` secret. Its own
history file is `data/plays-history.json`; the Round IQ workflow retains its
separate `data/tactics-history.json`.

The first five scenarios rotate through Mirage A, Inferno B, Dust II A, Ancient
B, and Anubis B. Each video animates five attackers, five defenders, a timed
flash cue, and the execute/retake phases over a CS2 radar.

These are illustrative tactical simulations. Player movement follows a
callout-anchored route animation and is not extracted from match demos or
validated against a map navmesh. Video overlays and descriptions identify the
content as a simulation, not real gameplay or a verified professional play.
