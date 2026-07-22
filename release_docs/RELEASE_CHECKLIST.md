# Release Checklist

Use this checklist for every tagged release.

- Update `VERSION` and the matching release status in `ROADMAP.md`.
- Update the changelog and version references in both root and packaged READMEs:
  - `README.md` must match `release_docs/README.md`.
  - `README_CN.md` must match `release_docs/README_CN.md`.
- Verify README parity before committing:
  - `git diff --no-index -- README.md release_docs/README.md`
  - `git diff --no-index -- README_CN.md release_docs/README_CN.md`
  - Both commands must produce no diff.
- Regenerate the bilingual User Guide PDF from the packaged READMEs using the established Pandoc + Edge headless flow.
- Run `python -m pytest tests` and require the full project suite to pass.
- Commit the release files, create the annotated version tag, push `main` and the tag, then verify the remote SHAs.
