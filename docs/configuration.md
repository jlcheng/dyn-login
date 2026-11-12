# Site configuration

This is the shape of the configuration object sent to `/<config_id>/configure`, either as base64 JSON in a GET link or as a JSON POST body. The server checks it with `validate_configuration` in `dyn_login/__init__.py`. That code is the source of truth, so update this page when it changes.

## Shape

Written in Zod 4 notation. The types cover what each field looks like. The rules after them cover what types can't express.

```ts
import { z } from "zod";

// An HTML element ID: nonempty, with no tab, line feed, form feed, carriage return, space, or NUL.
const ElementId = z.string().regex(/^[^\t\n\f\r \0]+$/);

// A PNG data URL. See the favicon rules below.
const Favicon = z.string().startsWith("data:image/png;base64,").max(2048);

// The original one-page format.
const FiveFieldConfig = z.strictObject({
  username_id: ElementId,
  password_id: ElementId,
  login_id: ElementId,
  expected_username: z.string(),
  expected_password: z.string(),
  favicon: Favicon.optional(),
});

const Credential = z.enum(["username", "password", "otp"]);

// One or more "/segment" parts. A segment uses A-Z a-z 0-9 . _ ~ - and doesn't start with ".".
const PagePath = z.string().regex(/^(\/[A-Za-z0-9_~-][A-Za-z0-9._~-]*)+$/);

const Page = z.strictObject({
  path: PagePath,
  fields: z.partialRecord(Credential, ElementId),
  submit_id: ElementId,
  bare_fields: z.array(Credential).optional(),
});

// The multi-page format.
const MultiPageConfig = z.strictObject({
  expected_credentials: z.partialRecord(Credential, z.string()),
  pages: z.array(Page).min(1),
  favicon: Favicon.optional(),
});

const SiteConfig = z.union([FiveFieldConfig, MultiPageConfig]);
```

Every object is strict: an unknown key makes the whole configuration invalid.

## Rules the types don't show

**Five-field format**

- `username_id`, `password_id`, and `login_id` must all be different.

**Multi-page format**

- `pages` is the login sequence, in array order.
- Page paths must be unique.
- `/profile`, `/logout`, and `/configure` can't be page paths. `/login` can be a page path only on the first page.
- `fields` must have at least one entry.
- Each credential appears on exactly one page. `username` and `password` are required; `otp` is optional.
- `expected_credentials` has exactly one value for each credential used on a page, no more and no fewer.
- On a page, the field IDs and `submit_id` must all be different. The same ID may be reused on different pages.
- `bare_fields` can't repeat a name, and every name in it must be a field on that same page. See [bare-fields.md](bare-fields.md).

**Favicon (both formats)**

- After the `data:image/png;base64,` prefix comes standard base64 (`+` and `/`, with `=` padding).
- The decoded bytes must be a PNG: the PNG signature, then an `IHDR` chunk.
- The width and height in that header must each be from 1 to 128.
- The 2,048-character cap keeps a configuration with a favicon small enough for a GET link. See the main README for tips on shrinking an icon.

## Outside the object

- The config ID in the URL uses A-Z a-z 0-9 `.` `_` `~` `-`, doesn't start with `.`, and is at most 128 characters.
- The server accepts query strings and POST bodies up to 64 KiB. In production, GET links are limited to 4,094 bytes for the whole request line. See [examples/README.md](../examples/README.md#size-limits).
- A rejected configuration returns HTTP 400 and leaves any existing configuration unchanged.

## Examples

- Five-field: the Python snippet in the main [README](../README.md#configure-your-own-page).
- Multi-page: [examples/multi-page.json](../examples/multi-page.json).
