# dyn-login bare fields: tech spec

## Summary

dyn-login can draw a login field with no hints, called a **bare field**, so login heuristics can't recognize the page. A page lists its bare fields in an optional `bare_fields` list. A username page whose only field is bare makes the `unmanaged` workflow throw `NoLoginFormFound` without typing anything, which is the intended result. A workflow recorded from the page still signs in, because it finds fields by element id rather than by hints.

## Details

**Hints.** Four things on an input tell the heuristics what it is: a `<label>`, a placeholder, an `autocomplete` value, and a credential-like `name` (such as `name="username"`). Earlier mock tests showed that any one of these alone is enough for the page to be read as a username page again. So a bare field must drop all four.

**Configuration.** In the multi-page format, a page may add `bare_fields`: a list of field names from that page's `fields`.

```json
{"path": "/login-step1", "fields": {"username": "un"}, "bare_fields": ["username"], "submit_id": "next-username"}
```

The configuration is rejected with a 400, and any existing configuration is left unchanged, when:

- `bare_fields` is not a list of strings,
- it repeats a name,
- it names a field that isn't on that page,
- the page has any other unknown key.

The older five-field format has no `bare_fields`.

**Rendering.** A bare field renders as `<input type="text" id="un" name="un">`. There's no label, no placeholder, and no `autocomplete`, and its `name` is its element id. The input keeps its normal `type`. The rest of the page is unchanged: the heading "Enter your username", "Step 1 of 2 · Username" in the step bar, and "Username ID" in the Form details panel. Fields not listed in `bare_fields` render as before.

**Sign-in.** The server reads a bare field's value from its element id, and every other field's value from its credential name, as before. Values are compared to `expected_credentials` the same way as today.

**Docs and tests.** `examples/README.md` gets one line describing `bare_fields`. The tests cover:

- rendering a bare field
- signing in through a bare username page
- a bare field next to a normal field
- the rejected configurations listed above

**Done when** the change is deployed to dyn-login.jcheng.org and the real extension shows the error on a two-page configuration with a bare username.

## Decisions

- **`bare_fields` is a per-page list, not a page-wide switch.** Hints belong to a field, and the list costs about the same code. Today the only real use is a bare username alone on its page.
- **The page's "Username" text stays.** The page that failed in the real extension kept the heading, step bar, and Form details text. Hiding them would make dyn-login's page differ from the one that was tested.
- **A bare field's `name` is its element id.** It needs some name that isn't a credential name, and the element id is already unique on the page.
- **Name collisions are not blocked.** A collision needs a bare field whose element id equals another field's credential name on the same page. That gives the bare field a credential-like `name`, which defeats the reason for making it bare, so nobody would configure it.
- **The visible "Try going manual" alert needs a catalog-app account,** such as the demo account. On an `unmanaged` account, you only get the `NoLoginFormFound` error.

## Not in scope

- Changing the extension or its heuristics.
- Bare password or verification-code fields. They're allowed by the configuration but not tested or targeted.
- Hiding the page's "Username" text.
- An editor template or preview demo for bare fields.
- How Scout records unlabeled fields.
- Accessibility of bare-field pages. They are test pages.
