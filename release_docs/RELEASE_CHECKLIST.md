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
- Regenerate the bilingual User Guide PDF from the packaged READMEs. Run both commands from
  `bashi-privacy-app/`; `<tmp>` is any scratch directory:

  ```sh
  # The separator is generated on the fly so the recipe needs no untracked file.
  printf '<div style="page-break-before: always;"></div>\n' > <tmp>/pagebreak.md

  # Drop line 1 of each README: it is the "English | 中文文档" switcher, whose
  # relative link only resolves when both files sit side by side. Printed into a
  # single bilingual PDF it becomes a link to a file that is not there, and the
  # reader warns before trying to open it. The PDF already holds both languages.
  tail -n +2 release_docs/README.md    > <tmp>/guide_en.md
  tail -n +2 release_docs/README_CN.md > <tmp>/guide_zh.md

  pandoc -s --metadata title="巴适声工厂隐私版使用手册 / Bashi Voice Factory Privacy Edition User Guide" \
    --metadata lang=zh-CN \
    <tmp>/guide_en.md <tmp>/pagebreak.md <tmp>/guide_zh.md \
    -o <tmp>/bashi_privacy_user_guide.html

  # Gate: no cross-file relative link may survive into the guide.
  grep -c 'href="README' <tmp>/bashi_privacy_user_guide.html   # must print 0

  msedge --headless=new --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="release_docs/巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf" \
    "file:///<tmp>/bashi_privacy_user_guide.html"
  ```

  Order is English, page break, Chinese. Pandoc warns that it cannot load `zh-CN` translations;
  that is harmless — these documents carry no abstract. Verify the result before committing:
  the guide must contain the mirror-fallback troubleshooting row and both `app.log` and
  `launch_log.txt` in the log-path guidance.
- **Third-party audio gate.** `static/audio/style_previews/` is the only audio directory the
  packaging script ships, and it is copied by a plain recursive filesystem copy
  (`Copy-RelativeDirectory` in `scripts/build_portable_zip.ps1`). That copy does not consult git,
  so **an untracked file dropped into that directory still ships**. Before every release:
  - Every file in `static/audio/style_previews/` must have a traceable origin and explicit
    redistribution rights. Reference human voices, user uploads, and any clone/voice-conversion
    derivative are barred from this directory.
  - Both commands must produce no output and no diff:

    ```sh
    git status --porcelain=v1 --untracked-files=all -- static/audio/style_previews
    git diff --quiet -- static/audio/style_previews
    ```

  - The portable build independently compares the staged file set with
    `git ls-files static/audio/style_previews/**`. Any extra or missing path is listed and aborts
    the build before compression; path separators and case are normalized for Windows.
  - Rights posture for generated audio: clone output can implicate source-material licensing,
    voice/personality rights, privacy, and copyright. **Until the rights status of a given clip is
    explicitly recorded, treat it as non-distributable.** A `.gitignore` entry only prevents
    accidental commits; it grants nothing and proves nothing about permission to use the material.
- Run `python -m pytest tests` and require the full project suite to pass.
- Commit the release files, create the annotated version tag, push `main` and the tag, then verify the remote SHAs.
