"""Shapes of the API's JSON results.

These are ``TypedDict``s: at run time every result is the plain ``dict`` (or
``list``) decoded from the response, so fields the API adds later are kept.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import IO, Any, Literal, Optional, TypedDict, Union

#: An image to send: a path, the encoded bytes, or a binary file object.
ImageInput = Union[str, "os.PathLike[str]", bytes, bytearray, memoryview, IO[bytes]]

#: An area as ``(x, y, width, height)`` in pixels, or the string ``"x,y,width,height"``.
Rect = Union[tuple[int, int, int, int], str]

#: A point as ``(x, y)`` in pixels, or the string ``"x,y"``.
Point = Union[tuple[float, float], str]

#: Parameters of a job's operation: a mapping of options, or a query string.
JobParams = Union[Mapping[str, Any], str]

Format = Literal["png", "jpg", "webp", "avif"]
Fit = Literal["contain", "cover", "fill"]
BarcodeEngine = Literal["auto", "zbar", "rxing"]
Region = Literal["background", "all"]
Align = Literal["center", "top", "bottom"]
Shadow = Literal["none", "contact", "drop"]
#: The model that finds the subject in ``remove_background``: ``"atlas"`` (the
#: API's default), ``"lumen"`` or ``"muse"``. Any other string is sent as it is,
#: so a model the API adds later works without a new release of this library.
BackgroundModel = Union[Literal["atlas", "lumen", "muse"], str]
CropFocus = Literal["subject", "face"]
WatermarkPosition = Literal[
    "top-left",
    "top",
    "top-right",
    "left",
    "center",
    "right",
    "bottom-left",
    "bottom",
    "bottom-right",
]
VectorizeMode = Literal["color", "mono"]
Curves = Literal["spline", "polygon", "pixel"]
BlurMode = Literal["blur", "pixelate", "fill"]
Pick = Literal["auto", "smallest", "largest"]
CaptionDetail = Literal["short", "detailed", "paragraph"]
HealthStatus = Literal["ok", "loading", "failed"]
Severity = Literal["info", "warning", "error"]
JobStatus = Literal["queued", "running", "completed"]
JobItemStatus = Literal["pending", "done", "failed"]

#: Step durations in milliseconds, by step name.
Timings = dict[str, int]


# --- account, presets, marketplaces, documents ----------------------------------------


class Account(TypedDict, total=False):
    account: str
    key: str
    credits: int
    prices: dict[str, int]
    unlimited: bool


class Preset(TypedDict):
    name: str
    description: str


class _MarketplaceProfileRequired(TypedDict):
    name: str
    title: str
    checked: str
    sources: list[str]
    rules: list[dict[str, Any]]
    fix: dict[str, Any]


class MarketplaceProfile(_MarketplaceProfileRequired, total=False):
    notes: list[str]


class _IdPhotoDocumentRequired(TypedDict):
    name: str
    title: str
    checked: str
    sources: list[str]
    notes: list[str]
    width_mm: float
    height_mm: float
    head_min_mm: float
    head_max_mm: float
    background: str


class IdPhotoDocument(_IdPhotoDocumentRequired, total=False):
    """A document with built-in photo rules, for ``id_photo``."""

    #: The eyes' smallest and largest distance from the bottom edge.
    eyes_from_bottom_mm: list[float]
    #: What the authority says about photos changed by software, in its own words.
    alteration: str


class WebhookSecret(TypedDict):
    secret: str
    header: str
    scheme: str


# --- barcodes, text -------------------------------------------------------------------


class _BarcodeRequired(TypedDict):
    format: str
    value: str


class Barcode(_BarcodeRequired, total=False):
    gs1: Optional[str]


class BarcodesResult(TypedDict):
    barcodes: list[Barcode]
    variant: str


class TextLine(TypedDict):
    text: str
    score: float
    box: list[list[float]]


class _TextResultRequired(TypedDict):
    lines: list[TextLine]


class TextResult(_TextResultRequired, total=False):
    ms: Timings


# --- palette, faces, caption ----------------------------------------------------------


class PaletteColor(TypedDict):
    hex: str
    rgb: list[int]
    share: float


class PaletteResult(TypedDict):
    width: int
    height: int
    colors: list[PaletteColor]


class FaceBox(TypedDict):
    x: float
    y: float
    width: float
    height: float


class FaceLandmarks(TypedDict):
    """Each an ``[x, y]`` pair. Right and left are the person's own."""

    right_eye: list[float]
    left_eye: list[float]
    nose: list[float]
    mouth_right: list[float]
    mouth_left: list[float]


class Face(TypedDict):
    box: FaceBox
    landmarks: FaceLandmarks
    score: float
    roll: float


class FacesResult(TypedDict):
    width: int
    height: int
    faces: list[Face]


class CaptionResult(TypedDict):
    caption: str
    detail: CaptionDetail
    width: int
    height: int


# --- check ----------------------------------------------------------------------------


class _FindingRequired(TypedDict):
    code: str
    severity: Severity
    message: str


class Finding(_FindingRequired, total=False):
    detail: str


class Border(TypedDict, total=False):
    mean: list[float]
    white: float
    cast: Optional[list[float]]


class Subject(TypedDict, total=False):
    x: int
    y: int
    width: int
    height: int
    fill: float
    area: float
    touches: list[str]
    background_white: float


class Metrics(TypedDict, total=False):
    width: int
    height: int
    sharpness: float
    noise: Optional[float]
    brightness: float
    highlights_clipped: float
    shadows_clipped: float
    brightest: float
    border: Border
    subject: Optional[Subject]


class CheckText(TypedDict, total=False):
    text: str
    on_product: Optional[bool]


class _VerdictRequired(TypedDict):
    marketplace: str
    passed: bool
    findings: list[Finding]
    not_checked: list[str]


class Verdict(_VerdictRequired, total=False):
    title: str
    notes: list[str]
    checked: str
    sources: list[str]


class _CheckResultRequired(TypedDict):
    metrics: Metrics
    findings: list[Finding]


class CheckResult(_CheckResultRequired, total=False):
    text: list[CheckText]
    marketplace: Verdict
    ms: Timings


# --- label ----------------------------------------------------------------------------


class Gs1(TypedDict, total=False):
    gtin: str
    batch: str
    serial: str
    expiry: str
    best_before: str
    production: str
    packed: str
    net_weight_kg: float
    count: int


class NetQuantity(TypedDict, total=False):
    value: float
    unit: str
    ml: float
    grams: float
    count: int
    text: str


class Alcohol(TypedDict, total=False):
    abv: float
    text: str


class LabelDate(TypedDict, total=False):
    kind: str
    date: str
    text: str


class Nutrition(TypedDict, total=False):
    per: str
    energy_kj: float
    energy_kcal: float
    fat: float
    saturates: float
    carbohydrate: float
    sugars: float
    fibre: float
    protein: float
    salt: float


class Material(TypedDict, total=False):
    name: str
    percent: float


class Electrical(TypedDict, total=False):
    voltage: str
    frequency: str
    power_w: float
    battery_mah: float


class LabelDetails(TypedDict, total=False):
    headline: list[str]
    gtin: str
    gs1: Gs1
    net_quantity: NetQuantity
    alcohol: Alcohol
    age_years: int
    vintage: int
    bottled: int
    dates: list[LabelDate]
    lot: str
    serial: str
    model: str
    ingredients: str
    allergens: list[str]
    may_contain: list[str]
    nutrition: Nutrition
    materials: list[Material]
    origin: str
    electrical: Electrical
    claims: list[str]


class _LabelResultRequired(TypedDict):
    label: LabelDetails
    barcodes: list[dict[str, Any]]
    text: list[str]


class LabelResult(_LabelResultRequired, total=False):
    ms: Timings


# --- identify -------------------------------------------------------------------------


class Candidate(TypedDict):
    product_id: str
    title: str
    score: float
    #: What agreed beyond the name: ``barcode``, ``barcode_text``, ``sku``,
    #: ``brand``, and by the catalogue's kind ``quantity``, ``pack``, ``spf``
    #: (food, cosmetics), ``strength``, ``count`` (pharmacy, household),
    #: ``spec``, ``model`` (electronics), ``cask_number``, ``age``,
    #: ``age_weak``, ``vintage``, ``abv``, ``size`` (wine and spirits).
    evidence: list[str]


class Measure(TypedDict):
    """A value read off a label, with its unit."""

    value: float
    unit: str


class IdentifyLabel(TypedDict, total=False):
    """Values read off the label; which ones depends on the catalogue's kind."""

    ages: list[int]
    weak_ages: list[int]
    years: list[int]
    abvs: list[float]
    #: Centilitres.
    sizes: list[float]
    #: Net quantities, in ``g`` or ``ml``.
    quantities: list[Measure]
    #: Units in a multipack: 6 for "6 x 330 ml".
    packs: list[int]
    #: Sun protection factors.
    spfs: list[int]
    #: Strengths of a medicine or supplement, in ``mg``, ``iu`` or ``percent``.
    strengths: list[Measure]
    #: Tablets, capsules, washes, rolls, wipes, batteries and the like in the pack.
    counts: list[int]
    #: Technical values, in ``gb``, ``mah``, ``wh``, ``w``, ``v``, ``a``, ``hz`` or ``in``.
    specs: list[Measure]


class _IdentifyResultRequired(TypedDict):
    catalogue: str
    candidates: list[Candidate]
    label: IdentifyLabel
    barcodes: list[str]


class IdentifyResult(_IdentifyResultRequired, total=False):
    text: str
    ms: Timings


# --- jobs -----------------------------------------------------------------------------


class JobCounts(TypedDict, total=False):
    total: int
    done: int
    failed: int
    pending: int


class ErrorDetail(TypedDict):
    """Why a job item failed. Besides the API's error codes, ``code`` may be
    ``input_unavailable``: the input URL could not be fetched."""

    code: str
    message: str


class _JobItemRequired(TypedDict):
    input: str
    status: JobItemStatus


class JobItem(_JobItemRequired, total=False):
    url: str
    result: str
    content_type: str
    bytes: int
    #: The result's headers, names in lower case: ``x-image-*``, ``server-timing`` and,
    #: on newer servers, the operation's own (``x-text-*``, ``x-marketplace-*``,
    #: ``x-subject-found``, ``x-paths``, ``x-faces``, ``x-faces-skipped``,
    #: ``x-select-score``, ``x-id-photo-*``).
    headers: dict[str, str]
    error: ErrorDetail


class JobWebhook(TypedDict, total=False):
    url: str
    attempts: int
    delivered: bool
    last_error: str


class _JobRequired(TypedDict):
    id: str
    operation: str
    params: str
    status: JobStatus
    created_at: int
    items: list[JobItem]
    counts: JobCounts


class Job(_JobRequired, total=False):
    finished_at: int
    webhook: JobWebhook


class JobSummary(TypedDict, total=False):
    id: str
    operation: str
    status: JobStatus
    created_at: int
    finished_at: Optional[int]
    counts: JobCounts


class WebhookEvent(TypedDict):
    """A verified webhook delivery, e.g. ``{"type": "job.completed", "job": {...}}``."""

    type: str
    job: Job


__all__ = [
    "Account",
    "Alcohol",
    "Align",
    "Barcode",
    "BarcodeEngine",
    "BarcodesResult",
    "BlurMode",
    "Border",
    "Candidate",
    "CaptionDetail",
    "CaptionResult",
    "CheckResult",
    "CheckText",
    "CropFocus",
    "Curves",
    "Electrical",
    "ErrorDetail",
    "Face",
    "FaceBox",
    "FaceLandmarks",
    "FacesResult",
    "Finding",
    "Fit",
    "Format",
    "Gs1",
    "HealthStatus",
    "IdPhotoDocument",
    "IdentifyLabel",
    "IdentifyResult",
    "ImageInput",
    "Job",
    "JobCounts",
    "JobItem",
    "JobItemStatus",
    "JobParams",
    "JobStatus",
    "JobSummary",
    "JobWebhook",
    "LabelDate",
    "LabelDetails",
    "LabelResult",
    "MarketplaceProfile",
    "Material",
    "Metrics",
    "NetQuantity",
    "Nutrition",
    "PaletteColor",
    "PaletteResult",
    "Pick",
    "Point",
    "Preset",
    "Rect",
    "Region",
    "Severity",
    "Shadow",
    "Subject",
    "TextLine",
    "TextResult",
    "Timings",
    "VectorizeMode",
    "Verdict",
    "WatermarkPosition",
    "WebhookEvent",
    "WebhookSecret",
]
