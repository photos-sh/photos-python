# photos-sh

Python client for the [Photos.sh](https://photos.sh) image API: background
removal, resizing and compression, AI upscaling, object and text removal,
light and colour fixes, cropping, watermarks, tracing into SVG, face tools
and identity photos, quality and marketplace checks with auto-fix, barcode
and label reading, captions, and batch jobs with webhooks.

Sync and asyncio clients, fully typed, one dependency
([httpx](https://www.python-httpx.org/)). Python 3.9 or newer.

## Install

```sh
pip install photos-sh
```

## Quick start

```python
from photos_sh import Photos

photos = Photos(api_key="...")  # or set PHOTOS_API_KEY

result = photos.remove_background("shoe.jpg")
result.save("shoe.png")
print(result.width, result.height, result.content_type)
```

With asyncio, the same methods are coroutines:

```python
import asyncio
from photos_sh import AsyncPhotos


async def main() -> None:
    async with AsyncPhotos() as photos:
        result = await photos.resize("shoe.jpg", width=800, format="webp")
        result.save("shoe.webp")


asyncio.run(main())
```

Both clients are context managers; without `with`, call `photos.close()`
(`await photos.aclose()` for the async client) when done.

## Images in, images out

An image argument is a path (`str` or `os.PathLike`), the encoded `bytes`, or
a binary file object:

```python
photos.resize("shoe.jpg", width=800)
photos.resize(Path("shoe.jpg"), width=800)
photos.resize(open("shoe.jpg", "rb"), width=800)
photos.resize(uploaded_bytes, width=800)
```

Options are keyword arguments named as in the
[API reference](https://photos.sh/docs/api); the ones you leave out are not
sent, so the API's defaults apply. A second image (`mask` of `erase`,
`watermark` of `watermark`, `background_image` of `remove_background`) is
given the same way as the first.

Methods that return an image give an `ImageResult`:

| Attribute | |
|---|---|
| `content` | the encoded image, as `bytes` |
| `content_type` | e.g. `image/png` |
| `width`, `height` | in pixels |
| `quality` | the quality used, for lossy formats; otherwise `None` |
| `server_timing` | the raw `Server-Timing` header (per-step durations) |
| `save(path)` | writes `content` to a file |

Some methods return a subclass with more to say about the result:

| Method | Result | Adds |
|---|---|---|
| `remove_background` | `RemoveBackgroundResult` | `subject_found` |
| `crop` | `CropResult` | `subject_found` |
| `remove_text` | `RemoveTextResult` | `removed`, `kept` |
| `fix` | `FixResult` | `passed`, `findings` |
| `vectorize` | `VectorizeResult` | `paths` |
| `blur_faces` | `BlurFacesResult` | `faces` |
| `restore_faces` | `RestoreFacesResult` | `faces`, `faces_skipped` |
| `id_photo` | `IdPhotoResult` | `passed`, `findings`, `head_mm` |
| `select` | `SelectResult` | `score` |

`subject_found` is `True`, `False`, or `None` when the API did not say.
`remove_background` only says `False`, and only when a canvas was asked for
and the photo has no subject: the canvas is then empty.

Methods that return JSON give the decoded `dict` or `list`, typed as a
`TypedDict` (`CheckResult`, `LabelResult`, `Job`, ...). Fields the API adds
later are kept.

## Methods

### Edit

```python
# Remove the background (transparent PNG by default).
cutout = photos.remove_background("shoe.jpg")
on_white = photos.remove_background(
    "shoe.jpg", format="jpg", background="white", crop=True, padding=40
)

# Stage the cutout in the same call: a canvas, a shadow or a reflection under
# the subject, and a colour, an image or the photo's own blurred background behind it.
staged = photos.remove_background(
    "shoe.jpg",
    width=1000,
    height=1000,
    fill=0.8,
    align="bottom",
    shadow="contact",
    reflection=True,
    background="white",
    format="jpg",
)
print(staged.subject_found)  # False when the photo has no subject: the canvas is then empty
on_beach = photos.remove_background("shoe.jpg", background_image="beach.jpg", shadow="drop")
soft = photos.remove_background("shoe.jpg", blur=40)

# Resize, convert and compress.
small = photos.resize("shoe.jpg", width=1200, height=1200, fit="cover", format="webp", quality=80)
light = photos.resize("shoe.jpg", width=1600, format="jpg", max_bytes=300_000)
# Cut away an even border first; write a print resolution into a JPEG or PNG.
print_ready = photos.resize("scan.jpg", trim=True, trim_tolerance=20, dpi=300)

# AI upscale, 1x to 4x.
big = photos.upscale("thumb.jpg", scale=2)

# Erase objects: rectangles (x, y, width, height) and/or a mask (white = remove).
clean = photos.erase("room.jpg", rect=[(40, 60, 200, 120), (500, 20, 80, 80)])
clean = photos.erase("room.jpg", mask="mask.png")

# Remove text, watermarks and captions. By default only text off the product goes.
result = photos.remove_text("listing.jpg")
print(result.removed, result.kept)  # lines removed, lines left alone
result = photos.remove_text("listing.jpg", region="all", matching=r"sale|www\.")

# Apply a built-in preset, or your own recipe (TOML).
main = photos.run("shoe.jpg", preset="marketplace")
custom = photos.run("shoe.jpg", recipe=open("recipe.toml").read())
```

Light, shape and marks:

```python
# Fix light and colour: automatic without settings, otherwise only what you give.
better = photos.enhance("shoe.jpg")
warmer = photos.enhance("shoe.jpg", auto=True, temperature=15, sharpen=30)

# Crop to a shape around the subject, keeping the background.
card = photos.crop("shoe.jpg", aspect="4:5")
print(card.subject_found)  # False when no subject was found: the crop is then centred
# focus="face" builds the crop around the faces: a portrait or an avatar.
avatar = photos.crop("team.jpg", width=400, height=400, focus="face", zoom=True, padding=0.6)

# Add a mark: text, or an image such as a logo.
marked = photos.watermark("shoe.jpg", text="© Acme", position="bottom-right", opacity=40)
marked = photos.watermark("shoe.jpg", watermark="logo.png", tile=True)

# Add room around the photo: to a shape, or by pixels on each side.
wide = photos.expand("shoe.jpg", aspect="16:9")
framed = photos.expand("shoe.jpg", left=100, right=100, fill="white")

# Trace a logo, an icon or a flat drawing into SVG.
traced = photos.vectorize("logo.png")
traced.save("logo.svg")
print(traced.paths, traced.width, traced.height)  # width and height: the size traced at
```

`watermark` text is drawn in Latin, Greek and Cyrillic letters only; a logo
has no such limit. `expand` continues the photo's background and does not
invent content: a subject cut off at the edge stays cut off. `vectorize` is
for flat artwork: a photograph traces into thousands of paths.

Clean up and restore:

```python
# Remove noise and JPEG artefacts.
clean = photos.denoise("grainy.jpg", strength=80)

# Colour a black-and-white photo.
coloured = photos.colorize("grandmother.jpg")

# Redraw the faces in an old or poor photo. The rest of it is not touched.
restored = photos.restore_faces("grandmother.jpg")
print(restored.faces, restored.faces_skipped)  # restored, and left alone as large enough
```

- `denoise` is slow without a GPU and takes photos up to 12 megapixels.
- `colorize` guesses the colours: skin, sky and grass come out believable,
  but the colour of clothes, cars or walls is invented.
- `restore_faces` invents the detail it draws. Do not use it where the face
  has to be exactly the person's own, such as an identity document or evidence.

Cut out one object:

```python
# The object at a point, or in a box (x, y, width, height). Pixels of the photo.
cup = photos.select("table.jpg", point=(420, 310))
print(cup.score)  # how well the model thinks the selection fits, 0 to 1
# More points add to the selection; exclude keeps something out of it.
cup = photos.select("table.jpg", point=[(420, 310), (455, 280)], exclude=(300, 310))
cup = photos.select("table.jpg", box=(350, 220, 180, 200), pick="largest")

# The mask is what erase takes to remove the object.
mask = photos.select("table.jpg", point=(420, 310), mask=True)
without = photos.erase("table.jpg", mask=mask.content)
```

Faces and identity photos:

```python
# Hide every face: mode is "blur", "pixelate" or "fill".
hidden = photos.blur_faces("street.jpg", mode="fill", color="black")
print(hidden.faces)  # how many were found and hidden

# Frame a portrait for an identity document: one of photos.id_photos(), or your sizes.
passport = photos.id_photo("portrait.jpg", document="uk-passport")
passport.save("passport.jpg")
print(passport.passed, passport.findings, passport.head_mm)
badge = photos.id_photo(
    "portrait.jpg",
    width_mm=35,
    height_mm=45,
    head_min_mm=32,
    head_max_mm=36,
    background="white",
)
```

- `blur_faces` hides only the faces it finds, so compare `faces` with the
  number of people you expect. Only `mode="fill"` leaves nothing of a face.
- `id_photo` keeps the photo's own background by default, because passport
  authorities do not accept edited photos. `background="white"` (or
  `"document"`) replaces it, for uses where that is allowed.
- `passed` says only that `findings` is empty. The tool cannot judge
  expression, glasses, shadows or likeness, so it is not an approval.

### Check and fix

```python
# Quality metrics and findings; with a marketplace, its verdict too.
report = photos.check("shoe.jpg", marketplace="amazon")
for finding in report["findings"]:
    print(finding["severity"], finding["code"], finding["message"])
print(report["marketplace"]["passed"])

# Product framing and text checks without a marketplace:
report = photos.check("shoe.jpg", subject=True, text=True)

# Make a photo meet a marketplace's rules.
fixed = photos.fix("shoe.jpg", "amazon")
fixed.save("shoe-amazon.jpg")
print(fixed.passed, fixed.findings)  # True, [] when nothing is left to fix
```

### Read

```python
codes = photos.read_barcodes("box.jpg")  # EAN-13, UPC-A, ITF-14
codes = photos.read_barcodes("box.jpg", all_formats=True)  # plus QR, Code 128, ...
for code in codes["barcodes"]:
    print(code["format"], code["value"])

text = photos.read_text("label.jpg")
for line in text["lines"]:
    print(line["text"], line["score"])

# Structured details from 1 to 8 photos of one product.
details = photos.read_label(["front.jpg", "back.jpg"])
print(details["label"].get("net_quantity"), details["label"].get("allergens"))

# Match 1 to 8 photos of one product against your organisation's catalogue
# (uploaded in the console; only for organisations it is turned on for).
match = photos.identify(["front.jpg", "back.jpg"], catalogue="shoes", top=3)
for candidate in match["candidates"]:
    print(candidate["title"], candidate["score"], candidate["evidence"])

# The main colours, the most common first.
palette = photos.palette("shoe.jpg", colors=5)
for colour in palette["colors"]:
    print(colour["hex"], colour["rgb"], colour["share"])

# Where the faces are: a box, five landmarks, a score and the tilt of each.
found = photos.find_faces("team.jpg")
for face in found["faces"]:
    print(face["box"], face["landmarks"]["nose"], face["score"], face["roll"])

# A description in English: "short" (the default), "detailed" or "paragraph".
described = photos.caption("shoe.jpg", detail="short")
print(described["caption"])
```

- `find_faces` finds faces. It does not recognise who anyone is.
- `caption` can be wrong (a colour, a count, what an object is) and is
  English only. Read the text before you publish it.

### Account and service

```python
photos.account()  # {"account": ..., "credits": ..., "prices": {...}}
photos.presets()  # [{"name": "marketplace", "description": ...}, ...]
photos.marketplaces()  # each marketplace's rules and what fix produces
photos.id_photos()  # the documents id_photo knows: sizes, notes and sources
photos.webhook_secret()  # {"secret": "whsec_...", "header": "Photos-Signature", ...}
photos.health()  # "ok", "loading" or "failed" (never raises for 503)
```

## Batch jobs

A job applies one operation to many images in the background. Inputs are
URLs the server fetches, images you upload, or both.

```python
job = photos.jobs.create(
    "remove-background",
    urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
    params={"format": "png", "crop": True},
    webhook_url="https://example.com/hooks/photos",  # optional
)

job = photos.jobs.wait(job["id"])  # polls every 2 s, for up to 10 minutes
print(job["counts"])  # {"total": 2, "done": 2, "failed": 0, "pending": 0}

for n, item in enumerate(job["items"]):
    if item["status"] == "done":
        photos.jobs.item(job["id"], n).save(f"out-{n}.png")
    else:
        print(item["input"], item["error"]["code"], item["error"]["message"])
```

A failed item's error code is one of the API's, or `input_unavailable` when
its URL could not be fetched.

Uploading the images instead:

```python
job = photos.jobs.create("resize", images=["a.jpg", "b.jpg"], params={"width": 800})
```

Looking after jobs:

```python
job = photos.jobs.get(job["id"])  # status, counts and items, without waiting
for summary in photos.jobs.list():  # recent jobs, newest first
    print(summary["id"], summary["status"], summary["counts"])
photos.jobs.delete(job["id"])  # cancels it if unfinished; removes its results
```

Operations: `run`, `remove-background`, `resize`, `upscale`, `ocr`,
`barcodes`, `check`, `fix`, `remove-text`, `label`, `enhance`, `crop`,
`palette`, `watermark`, `expand`, `vectorize`, `faces`, `blur-faces`,
`id-photo`, `denoise`, `colorize`, `select`, `restore-faces`, `caption`.
`params` are that operation's options, as a mapping or a query string
(`"width=800"`); `run` takes `params={"preset": "marketplace"}` or
`recipe="..."`.

A job item is one image. So a `watermark` job takes `text` only, and a
`remove-background` job no background image. An option that repeats is a
list, and a point is the string `"x,y"`:

```python
job = photos.jobs.create(
    "select", images=["a.jpg", "b.jpg"], params={"point": ["420,310", "455,280"]}
)
```

| Method | |
|---|---|
| `jobs.create(operation, *, urls=None, images=None, params=None, recipe=None, webhook_url=None)` | start a job |
| `jobs.get(job_id)` | status, counts and per-item results |
| `jobs.list()` | your recent jobs, newest first |
| `jobs.wait(job_id, *, poll_interval=2.0, timeout=600.0)` | poll until completed; `JobTimeoutError` when time is up |
| `jobs.item(job_id, n)` | the result of item `n` (from 0) |
| `jobs.delete(job_id)` | cancel if unfinished, and delete |

`jobs.item` returns a `JobItemResult`: an `ImageResult` (with `save`) that
also has `headers`, `is_image`, `is_json` and, for operations that produce
JSON (`ocr`, `barcodes`, `check`, `label`, `palette`, `faces`, `caption`),
`json()`:

```python
lines = photos.jobs.item(job["id"], 0).json()["lines"]
```

Items of the operations whose result says more than the image convert to
the same results the synchronous methods return:

```python
fixed = photos.jobs.item(fix_job["id"], 0).fix()  # a FixResult
print(fixed.passed, fixed.findings)

cleaned = photos.jobs.item(text_job["id"], 0).remove_text()  # a RemoveTextResult
print(cleaned.removed, cleaned.kept)

print(photos.jobs.item(cutout_job["id"], 0).remove_background().subject_found)
print(photos.jobs.item(crop_job["id"], 0).crop().subject_found)
print(photos.jobs.item(trace_job["id"], 0).vectorize().paths)
print(photos.jobs.item(blur_job["id"], 0).blur_faces().faces)
print(photos.jobs.item(restore_job["id"], 0).restore_faces().faces_skipped)
print(photos.jobs.item(id_job["id"], 0).id_photo().findings)
print(photos.jobs.item(select_job["id"], 0).select().score)
```

Each raises `PhotosError` when the item does not carry that operation's
headers: it came from another operation, or from an older server that does
not keep them on job items. Only `remove_background()` does not raise: the
API sends its header for an empty canvas alone, so `subject_found` is
`False` then and `None` otherwise. The same values are in the job itself, as
`job["items"][n]["headers"]` (lower-case names, e.g. `x-marketplace-passed`,
`x-faces`).

A completed job may contain failed items: check `job["counts"]["failed"]`.

## Webhooks

Pass `webhook_url` when creating a job and the API posts a signed
`job.completed` event there. Verify it with the raw request body, the
`Photos-Signature` header and your signing key (`photos.webhook_secret()["secret"]`,
stable per account: fetch it once and keep it with your other secrets):

```python
from photos_sh import WebhookVerificationError, webhooks


def handle(raw_body: bytes, headers) -> int:
    try:
        event = webhooks.verify(raw_body, headers.get("Photos-Signature"), WEBHOOK_SECRET)
    except WebhookVerificationError:
        return 400
    if event["type"] == "job.completed":
        job = event["job"]
        print(job["id"], job["counts"])
    return 200
```

`verify(body, header, secret, tolerance=300, now=None)` recomputes the
HMAC-SHA256 signature, compares it in constant time, and rejects deliveries
whose timestamp is more than `tolerance` seconds from now. Pass the body
exactly as received, not re-encoded JSON.

## Errors

Everything the library raises derives from `PhotosError`.

```python
from photos_sh import APIConnectionError, APIError, BusyError, PaymentRequiredError

try:
    photos.upscale("thumb.jpg")
except PaymentRequiredError:
    ...  # out of credits
except BusyError as e:
    ...  # still busy after the retries; e.retry_after is in seconds
except APIError as e:
    print(e.status, e.code, e.message)
except APIConnectionError:
    ...  # no response (APITimeoutError when it timed out)
```

An `APIError` has `status`, `code` (the API's error code, `None` if the
response was not the API's JSON), `message`, `retry_after` and `body`.
The subclasses follow the code. A response without one is a plain
`APIError` (a `404` for a wrong base URL, a proxy's `502`), or the subclass
for its status where that is unambiguous (400, 401, 402, 403, 413, 415,
422, 500).

| Class | Status | Code |
|---|---|---|
| `BadRequestError` | 400 | `bad_request` |
| `AuthenticationError` | 401 | `unauthorized` |
| `PaymentRequiredError` | 402 | `payment_required` |
| `AccountSuspendedError` | 403 | `account_suspended` |
| `NotFoundError` | 404 | `not_found` |
| `PayloadTooLargeError` | 413 | `payload_too_large` |
| `UnsupportedFormatError` | 415 | `unsupported_format` |
| `UnprocessableError` | 422 | `unprocessable` |
| `InternalServerError` | 500 | `internal` |
| `BusyError` | 503 | `busy` |
| `ModelUnavailableError` | 503 | `model_unavailable` |

Other errors: `APIConnectionError` and its subclass `APITimeoutError`,
`JobTimeoutError` (from `jobs.wait`; `.job` is the last state seen),
`WebhookVerificationError`. Wrong arguments (no API key aside) raise the
usual `ValueError` or `TypeError` before anything is sent.

## Configuration

```python
photos = Photos(
    api_key="...",  # default: PHOTOS_API_KEY
    base_url="https://api.photos.sh",  # default: PHOTOS_BASE_URL, then this
    timeout=120.0,  # seconds, or an httpx.Timeout
    max_retries=2,
    http_client=None,  # your own httpx.Client
)
```

- **Retries.** A `503` is retried up to `max_retries` times, waiting the
  `Retry-After` the API gives (at most 30 s), else 1 s then 2 s. Failures to
  connect are retried the same way, except when creating a job. Nothing else
  is retried: not other statuses, not a `503` with another error code
  (`model_unavailable` is permanent), not a request that timed out waiting
  for the answer.
- **Timeout.** Model work takes seconds, so the default is 120 s.
- **Your own HTTP client.** Pass an `httpx.Client` (`httpx.AsyncClient` to
  `AsyncPhotos`) for proxies, custom transports or connection limits. It
  keeps its own timeout unless you also pass `timeout`, and it is not closed
  by the library.
- `AsyncPhotos` runs on asyncio. Paths and file objects are read on the
  calling thread before the request is sent; pass `bytes` if that matters.

## Development

```sh
uv sync
uv run pytest               # unit tests, no network needed
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Integration tests run against a real engine when both variables are set:

```sh
PHOTOS_TEST_BASE_URL=http://127.0.0.1:8098/api PHOTOS_TEST_API_KEY=... uv run pytest tests/test_integration.py
```

## License

MIT. See [LICENSE](LICENSE).
