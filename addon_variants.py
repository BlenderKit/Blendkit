import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit


def public_variants(asset):
    return [
        variant
        for variant in asset.get("variants", []) or []
        if not variant.get("isPrivate") and variant.get("id")
    ]


def variant_price(variant):
    if variant.get("isFree"):
        return "Free"
    if variant.get("canDownload") and variant.get("isForSale"):
        return "Purchased"
    price = variant.get("userPrice", variant.get("basePrice"))
    return f"${price}" if price is not None else variant.get("accessLabel", "Paid")


@lru_cache(maxsize=128)
def variant_enum_items(asset_json):
    return [
        (
            variant["id"],
            f"{variant.get('displayName', variant.get('name', 'Variant'))} - {variant_price(variant)}",
            variant.get("description", ""),
        )
        for variant in public_variants(json.loads(asset_json or "{}"))
    ]


def variant_summary(asset):
    variants = public_variants(asset)
    if not variants:
        return ""
    parts = [f"{len(variants)} variant{'s' if len(variants) != 1 else ''}"]
    if any(variant.get("isFree") for variant in variants):
        parts.append("Free available")
    prices = []
    for variant in variants:
        if not variant.get("isForSale"):
            continue
        try:
            price = Decimal(str(variant.get("userPrice", variant.get("basePrice"))))
            if price.is_finite() and price >= 0:
                prices.append(price)
        except InvalidOperation:
            pass
    if prices:
        parts.append(f"From ${min(prices):.2f}")
    return " | ".join(parts)


def selected_variant(asset, variant_id=""):
    variants = public_variants(asset)
    if not variants:
        return None
    variant_id = variant_id or asset.get("selectedVariantId", "")
    return next(
        (variant for variant in variants if variant["id"] == variant_id),
        next(
            (variant for variant in variants if variant.get("isDefault")), variants[0]
        ),
    )


def resolve_variant(asset, variant_id="", server=""):
    variant = selected_variant(asset, variant_id)
    if variant is None:
        return asset
    resolved = {
        key: value
        for key, value in asset.items()
        if key
        not in {
            "variants",
            "selectedVariantId",
            "canDownload",
            "canDownloadError",
            "userPrice",
            "basePrice",
            "files",
            "filesSize",
            "dictParameters",
            "addonArchive",
            "tooltip_data",
        }
    }
    resolved.update(variant)
    resolved["parentAssetBaseId"] = asset["assetBaseId"]
    resolved["structure"] = "variant"
    resolved["canDownload"] = variant.get("canDownload", bool(variant.get("isFree")))
    resolved["dictParameters"] = dict(variant.get("dictParameters", {}))
    resolved["available_resolutions"] = []
    files = [dict(file) for file in variant.get("files", [])]
    for file in files:
        url = file.get("downloadUrl", "")
        if server and url.startswith("SCHEME://DOMAIN/"):
            file["downloadUrl"] = server.rstrip("/") + urlsplit(url).path
    resolved["files"] = files
    resolved["filesSize"] = (
        sum(file.get("fileUploadSize", 0) or 0 for file in files) // 1024
    )
    return resolved


def consolidate_addon_variants(assets):
    parents = {}
    owners = {}
    for asset in assets:
        if (
            asset.get("assetType") != "addon"
            or asset.get("structure") != "variant_parent"
        ):
            continue
        parent_key = asset.get("assetBaseId") or asset.get("id")
        parent = parents.setdefault(parent_key, asset)
        for variant in asset.get("variants", []) or []:
            for key in ("id", "assetBaseId"):
                if variant.get(key):
                    owners[(key, variant[key])] = parent

    consolidated = []
    seen_parents = set()
    for asset in assets:
        parent = None
        if asset.get("assetType") == "addon":
            if asset.get("structure") == "variant_parent":
                parent = parents[asset.get("assetBaseId") or asset.get("id")]
            elif asset.get("structure") == "variant":
                parent = owners.get(("id", asset.get("id"))) or owners.get(
                    ("assetBaseId", asset.get("assetBaseId"))
                )
        if parent is None:
            consolidated.append(asset)
            continue
        parent_key = parent.get("assetBaseId") or parent.get("id")
        if parent_key not in seen_parents:
            consolidated.append(parent)
            seen_parents.add(parent_key)
    return consolidated


def variant_gallery_url(parent_url, variant):
    url = urlsplit(parent_url)
    query = dict(parse_qsl(url.query, keep_blank_values=True))
    query["variant"] = variant["assetBaseId"]
    return url._replace(query=urlencode(query)).geturl()
