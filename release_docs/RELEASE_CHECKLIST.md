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
  # Both helper files are generated on the fly so the recipe needs no untracked file.
  printf '<div style="page-break-before: always;"></div>
' > <tmp>/pagebreak.md

  # A4 with explicit margins, and a CJK-capable font stack. Without this the
  # printer falls back to Letter.
  cat > <tmp>/header.html <<'CSS'
  <style>
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; line-height: 1.55; }
  code, pre { font-family: Consolas, "Cascadia Mono", monospace; }
  pre { white-space: pre-wrap; word-wrap: break-word; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #bbb; padding: 4px 7px; vertical-align: top; }
  h1, h2, h3 { page-break-after: avoid; }
  img { max-width: 100%; }
  </style>
  CSS

  # Drop line 1 of each README: it is the "English | 中文文档" switcher, whose
  # relative link only resolves when both files sit side by side.
  tail -n +2 release_docs/README.md    > <tmp>/guide_en.md
  tail -n +2 release_docs/README_CN.md > <tmp>/guide_zh.md

  pandoc -s -H <tmp>/header.html \
    --metadata title="巴适声工厂隐私版使用手册 / Bashi Voice Factory Privacy Edition User Guide" \
    --metadata lang=zh-CN \
    <tmp>/guide_en.md <tmp>/pagebreak.md <tmp>/guide_zh.md \
    -o <tmp>/guide_raw.html

  # Rewrite every remaining relative link to an absolute HTTPS address BEFORE
  # printing. This is the whole defect: the headless printer resolves href="LICENSE"
  # against the scratch directory, so v0.1.1-v0.1.3 shipped links pointing at the
  # build machine. Different generators produced different forms of the same bug
  # (file:///C:/... and http://markdownpanel-virtualhost/...), which is why the
  # gate below rejects everything that is not HTTPS rather than just "file:".
  GH=https://github.com/gtree965/bashi-voice-factory-privacy/blob/main
  sed -e "s|href=\"LICENSE\"|href=\"$GH/LICENSE\"|g" \
      -e "s|href=\"VERSION\"|href=\"$GH/VERSION\"|g" \
      <tmp>/guide_raw.html > <tmp>/bashi_privacy_user_guide.html

  # Gate 1 (HTML): no non-HTTPS link may survive. Anchors and the author mailto
  # are the only exceptions.
  grep -o -E 'href="[^"]*"' <tmp>/bashi_privacy_user_guide.html \
    | grep -v -E '^href="(https://|#|mailto:ncorecpu@gmail\.com")' | grep -c .   # must print 0

  msedge --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header \
    --print-to-pdf="release_docs/巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf" \
    "file:///<tmp>/bashi_privacy_user_guide.html"

  # Gate 2 (PDF): parses the finished file and fails closed. Also enforced by
  # build_portable_zip.ps1 before and after staging, so a stale PDF cannot ship.
  .venv/Scripts/python.exe -m pip install -r requirements-build.txt   # once
  .venv/Scripts/python.exe scripts/check_pdf_links.py \
    "release_docs/巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf"
  ```

  Order is English, page break, Chinese. Pandoc warns that it cannot load `zh-CN` translations;
  that is harmless — these documents carry no abstract. Verify the result before committing:
  A4 page size, Chinese text rendering without tofu boxes, no table split mid-row, the
  mirror-fallback troubleshooting row present, and both `app.log` and `launch_log.txt` in the
  log-path guidance.
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
