# Typewriter ↔ AnkiAutomata integration handoff

## Goal and current implementation

Let a word move between spelling practice in Typewriter and reviewed Anki card creation in AnkiAutomata, carrying its sentence context without overwriting an existing word or review history.

The AnkiAutomata side is implemented. No Typewriter source files or personal notebook data have been changed. The current Typewriter API was inspected in `typewriter/web.py`, `typewriter/store.py`, and `templates/index.html` in the sibling Typewriter repository.

### Already working: AnkiAutomata → Typewriter

AnkiAutomata's **Send to Typewriter** button sends the currently reviewed word and definition, plus the user's sentence. If the sentence field is empty, it uses the first edited example containing the exact word. The Anki draft stays open after sending.

The adapter in `typewriter_client.py` uses Typewriter's existing API:

1. `GET /api/health`; require `app == "typewriter"`.
2. `GET /`; obtain the existing `meta[name="typewriter-token"]` content.
3. `POST /api/words` with `X-Typewriter-Token` and the matching local Origin header:

```json
{
  "words": [{
    "word": "serendipity",
    "definition": "a happy discovery",
    "sentence": "It was pure serendipity.",
    "tag": "AnkiAutomata"
  }]
}
```

A successful response is HTTP 201 with `{"added": [123], "duplicates": []}`. For an existing word, the response is `{"added": [], "duplicates": ["serendipity"]}`. AnkiAutomata reports that the word already exists and does not issue a PATCH, reset its schedule, or change its existing material.

The adapter honors the current English-word validation, 80-character word limit, and 2,000-character definition/sentence limits. It reports validation failures instead of silently truncating content. Imports may remain pending because no spelling tip is fabricated. Typewriter retains responsibility for its own preparation queue and pronunciation verification.

The default address is `http://127.0.0.1:8080`; AnkiAutomata's `preferences.typewriter_url` can select another loopback HTTP port. Redirects and remote host addresses are rejected. Tokens are fetched per operation and are not saved or logged.

This flow has been verified against Typewriter's actual Flask application using a temporary notebook, background preparation disabled, and an ephemeral loopback port. It created one word, recognized the repeat, and preserved the existing definition, stage, due time, and creation time.

## Requested Typewriter work: Open in AnkiAutomata

Add **Open in AnkiAutomata** to the word editor and notebook word actions. Send the selected word and its saved sentence to AnkiAutomata for review. Do not automatically add an Anki note, start a practice answer, or change the Typewriter word's schedule.

### UI behavior

- Place the action near the dictionary/material controls in the word editor and in the word-row action menu.
- Disable repeat submissions while the request is pending.
- On success, report “Opened in AnkiAutomata. Review the card there.”
- If AnkiAutomata is unavailable, explain how to start it and allow retry. Keep the Typewriter editor open and preserve unsaved changes.
- For an unsaved word-editor draft, either send its current word/sentence explicitly or require saving first; make the chosen behavior visible.
- Anki duplicates remain AnkiAutomata's responsibility. It will show a preview and an Open in Anki action.

### Server-side proxy

Implement a token-protected route such as:

```http
POST /api/integrations/ankiautomata/lookup
X-Typewriter-Token: <existing local browser token>
Content-Type: application/json

{"word_id": 123}
```

Use Typewriter's existing `protect_local_app` checks. Resolve the word and sentence from its own store, then forward them server-side. For unsaved drafts, validate explicit `word` and `sentence` fields using the same limits as the editor. Do not have browser JavaScript call AnkiAutomata directly or relax either app's browser-origin policy.

Check the peer with:

```http
GET http://127.0.0.1:24536/health
```

Expected JSON:

```json
{
  "app": "ankiautomata",
  "api_version": 1,
  "capabilities": ["lookup", "sentence", "activate"]
}
```

Then send:

```http
POST http://127.0.0.1:24536/lookup
Content-Type: application/json; charset=utf-8

{"text": "serendipity", "sentence": "It was pure serendipity."}
```

Contract:

- HTTP 200, plain text `Lookup queued`: the request was queued for the GUI, not added to Anki.
- HTTP 400: invalid JSON, missing/empty text, or a non-string sentence.
- HTTP 413: body is empty or exceeds 4,096 bytes. Count UTF-8 JSON bytes, not just characters.
- HTTP 429: the lookup queue is full; offer a later retry.
- Send `sentence: ""` to clear prior sentence context. Omitting `sentence` preserves the app's existing context.
- Text-only clients using `{"text": "word"}` remain supported.
- The receiver normalizes PDF whitespace, focuses its window, searches the word, and preserves the supplied sentence in the draft/history.
- The receiver processes the request on Tk's main thread. Lookups received during an Anki export wait until the export finishes.

Use short connection/read timeouts and no environment proxy for this local request. Keep the target restricted to loopback. Port configuration can be supported if needed; no laptop LAN listener is required.

### Optional cold start

AnkiAutomata also provides a CLI that accepts word/context directly and starts its GUI when necessary:

```bash
/path/to/AnkiAutomata/envAnkiAutomata/bin/python /path/to/AnkiAutomata/shortcut.py \
  --text=serendipity --sentence="It was pure serendipity."
```

If offering automatic launch, let the user configure the AnkiAutomata directory/interpreter. Invoke an argument array with `shell=False`, using `--text=<word>` and `--sentence=<sentence>` as individual arguments. Do not interpolate notebook text into a shell command or assume Typewriter's virtual environment contains CustomTkinter/Pygame/Pillow.

Cold start should be optional. The initial implementation can require the user to open AnkiAutomata and show a useful unavailable message instead.

## Optional later improvements

These are not prerequisites for the current integration:

- Add visible import provenance for AnkiAutomata imports; the existing add-words API currently labels provided material as manual.
- If introducing a dedicated import endpoint, keep `/api/words` compatible until a versioned capability handshake is coordinated with AnkiAutomata.
- Coordinate pronunciation metadata separately. Never mark imported or automatically fetched audio as user-verified. Typewriter's existing checked-voice workflow should continue to govern audio-only exercises.
- Do not share either app's SQLite files, cache files, API keys, or internal settings as the integration transport.

## Acceptance checks for the Typewriter team

1. A selected word and sentence arrive in AnkiAutomata unchanged apart from whitespace normalization.
2. An empty sentence clears prior context, while an omitted sentence leaves it alone.
3. Requests from a foreign browser origin or without Typewriter's CSRF token remain rejected.
4. A closed peer, wrong application on the port, timeout, oversized request, or full queue produces a useful retryable message without losing editor changes.
5. No Anki note is added until the user confirms in AnkiAutomata.
6. Repeated Typewriter imports keep one notebook word and preserve its existing clues, ratings, stage, and due time.
7. Quotes, apostrophes, non-ASCII sentence text, and shell metacharacters are handled as data.
8. Test with temporary notebooks and fake/ephemeral peer servers; avoid the user's real notebook and Anki collection.

## Reproduce the integration check

From the AnkiAutomata repository, using Typewriter's own Python environment:

```bash
../Typewriter/.venv/bin/python tests/typewriter_integration.py --typewriter-root ../Typewriter
```

The runner disables bytecode writes into the sibling source tree and uses a temporary notebook without loading the user's API-key file or running background preparation.
