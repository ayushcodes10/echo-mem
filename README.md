# CLA signatures

Storage branch for `.github/workflows/cla.yml`. It holds one file,
`signatures/version1/cla.json`, which the CLA action appends to when a
contributor signs in a pull request thread.

Created 2026-08-28 because the action does not create this branch itself: it
fails with "Branch cla-signatures not found", and that failure blocks the check
on every pull request rather than merely posting a wrong comment. Do not
protect this branch - the action needs to push to it.

Nothing here is edited by hand.
