# Changelog

All notable changes to this library are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the library
follows [Semantic Versioning](https://semver.org/).

## 1.0.0 (unreleased)

First version.

- `identify` matches against the organisation's own catalogues (uploaded in
  the console; turned on per organisation). Without it the API answers
  `404 not_found` (`NotFoundError`). A catalogue is one of seven kinds of
  product, and the evidence and the label's values follow it: `sku`, `brand`,
  `quantity`, `pack`, `spf`, `strength`, `count`, `spec`, `model` beside the
  wine and spirits ones.
- `Photos` (sync) and `AsyncPhotos` (asyncio) clients for every endpoint of
  the Photos.sh API: remove background, resize, upscale, erase, remove text,
  run (presets and recipes), fix, check, read barcodes, read text, read
  label, identify, account, presets, marketplaces, health, webhook secret.
- The API's newer tools: `enhance`, `crop`, `watermark` (text or an image),
  `expand`, `vectorize`, `blur_faces`, `id_photo`, `denoise`, `colorize`,
  `select` and `restore_faces`; `palette`, `find_faces` and `caption`, which
  return JSON; and `id_photos`, the documents `id_photo` knows.
- `remove_background` can stage the cutout: `width`, `height`, `fill`,
  `align`, `shadow`, `reflection`, `blur` and `background_image` (sent as
  the `background` part). `resize` takes `trim`, `trim_tolerance` and `dpi`.
- Batch jobs: `jobs.create`, `get`, `list`, `delete`, `item` and `wait`.
  In a job's `params`, an option that repeats (`point` and `exclude` of
  `select`) is a list.
- `JobItemResult.remove_text()` and `.fix()` give the typed results of
  `remove-text` and `fix` jobs (`removed`/`kept`, `passed`/`findings`), and
  raise `PhotosError` when the server did not keep those headers on the item.
  `.crop()`, `.vectorize()`, `.blur_faces()`, `.restore_faces()`,
  `.id_photo()` and `.select()` do the same for those jobs.
  `.remove_background()` gives `subject_found` and does not raise, because
  the API sends that header only for an empty canvas.
- Typed results: `ImageResult` and its subclasses for images
  (`RemoveBackgroundResult` and `CropResult` with `subject_found`,
  `RemoveTextResult`, `FixResult`, `VectorizeResult` with `paths`,
  `BlurFacesResult` with `faces`, `RestoreFacesResult` with `faces` and
  `faces_skipped`, `IdPhotoResult` with `passed`, `findings` and `head_mm`,
  `SelectResult` with `score`), `TypedDict`s for JSON.
- Typed errors by API error code; retries for `503` and connection failures.
- `photos_sh.webhooks.verify` for webhook deliveries.
