# Manual downloads drop folder

Official files that the build could not fetch with a plain request (portal returned 403, a bot
challenge, a TLS error, or no text layer). A teammate downloads them in a normal browser from the
official page and saves them here as:

    kb/raw/manual/<doc_id>.pdf        English (or the only language)
    kb/raw/manual/<doc_id>.ar.pdf     Arabic original

`<doc_id>` must match `kb/sources/manifest.csv`. `.html` is also accepted. Then run:

    .venv/bin/python scripts/build_kb.py --no-download

A file here overrides any automatically downloaded copy of the same doc_id/language
(status becomes `manual_ok`). Official sources only, never a law-firm copy or unofficial mirror.
See `kb/sources/MANUAL_DOWNLOADS.md` for the checklist.
