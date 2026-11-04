"""Small LCSC search/detail client adapted from the user's lcsc_tool.py.

Origin: altium-delphiscript-toolkit/lcsc_tool.py, LcscClient and
component_from_payload. Only catalog HTTP requests, field parsing and quantity
pricing are retained; this module has no Altium, CLI, cache or job dependencies.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import re
import time
from urllib import error, parse, request


BASE_URL = "https://wmsc.lcsc.com/ftps/wm"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
CODE = re.compile(r"C[0-9]+", re.IGNORECASE)


class LcscError(RuntimeError):
    """An HTTP, upstream schema or missing-product failure."""


def validate_quantity(qty):
    if type(qty) is not int or not 1 <= qty <= 1_000_000_000:
        raise ValueError("qty must be an integer from 1 to 1000000000")


def validate_code(value):
    if not isinstance(value, str) or not CODE.fullmatch(value.strip()):
        raise ValueError("lcsc_id must be an exact LCSC code such as C136648")
    return value.strip().upper()


def clean_text(value):
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def number(value, integer=False):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
        if not math.isfinite(result) or result < 0 or (integer and not result.is_integer()):
            return None
        return int(result) if integer else result
    except (ValueError, TypeError, OverflowError):
        return None


def first_value(values, keys):
    for key in keys:
        if values.get(key) is not None and values[key] != "":
            return values[key]
    return None


def http_url(value):
    value = clean_text(value)
    if value.startswith("//"):
        value = "https:" + value
    try:
        url = parse.urlsplit(value)
        return value if url.scheme.lower() in {"http", "https"} and url.netloc else ""
    except ValueError:
        return ""


def component_from_payload(payload, qty=1):
    """Retain catalog parameter names/units; do not infer electrical ratings."""
    validate_quantity(qty)
    if not isinstance(payload, dict):
        raise LcscError("LCSC product is not a JSON object")
    try:
        lcsc_id = validate_code(payload.get("productCode"))
    except ValueError as exc:
        raise LcscError("LCSC product has no valid productCode") from exc
    mpn = clean_text(payload.get("productModel"))
    if not mpn:
        raise LcscError("LCSC product has no manufacturer part number")
    raw_prices = payload.get("productPriceList") or payload.get("priceList") or []
    if not isinstance(raw_prices, list):
        raise LcscError("LCSC product price list has an unsupported schema")
    prices = []
    for row in raw_prices:
        if not isinstance(row, dict):
            continue
        quantity = number(first_value(row, ("ladder", "startPurchasedNumber", "quantity")), integer=True)
        price = number(first_value(row, ("currencyPrice", "productPrice", "usdPrice")))
        if quantity and price is not None:
            prices.append({"quantity": quantity, "unit_price": price, "currency": "USD"})
    prices.sort(key=lambda row: row["quantity"])
    raw_parameters = payload.get("paramVOList") or payload.get("paramPOList") or []
    if not isinstance(raw_parameters, list):
        raise LcscError("LCSC product parameters have an unsupported schema")
    parameters = {}
    for row in raw_parameters:
        if not isinstance(row, dict):
            continue
        name = clean_text(row.get("paramNameEn") or row.get("paramName"))
        value = clean_text(first_value(row, ("paramValueEn", "paramValue")))
        if name and value and value != "-":
            parameters[name] = value
    category_path = []
    for level in ("first", "second", "third", "fourth", "fifth", "sixth"):
        name = clean_text(payload.get(level + "WmCatalogNameEn"))
        if name and name not in category_path:
            category_path.append(name)
    category = clean_text(payload.get("wmCatalogNameEn") or payload.get("catalogName") or
                          (category_path[-1] if category_path else ""))
    if category and (not category_path or category_path[-1] != category):
        category_path.append(category)
    moq = number(first_value(payload, ("minBuyNumber", "minPacketNumber")), integer=True)
    moq = max(1, moq) if moq is not None else None
    order_qty = max(qty, moq) if moq is not None else None
    applicable = [row for row in prices if order_qty is not None and row["quantity"] <= order_qty]
    unit_price = applicable[-1]["unit_price"] if applicable else None
    batch_cost = float(Decimal(str(unit_price)) * order_qty) if unit_price is not None else None
    if batch_cost is not None and not math.isfinite(batch_cost):
        batch_cost = None
    return {
        "lcsc_id": lcsc_id, "mpn": mpn,
        "manufacturer": clean_text(payload.get("brandNameEn") or payload.get("brandName")),
        "category": category, "category_path": category_path,
        "description": clean_text(payload.get("productIntroEn") or payload.get("productNameEn") or payload.get("productDescEn")),
        "package": clean_text(payload.get("encapStandard")),
        "stock": number(payload.get("stockNumber"), integer=True), "moq": moq,
        "prices": prices, "currency": "USD", "requested_qty": qty, "order_qty": order_qty,
        "unit_price": unit_price, "batch_cost": batch_cost,
        "datasheet_url": http_url(payload.get("pdfUrl") or payload.get("pdfURL")),
        "product_url": f"https://www.lcsc.com/product-detail/{lcsc_id}.html",
        "parameters": parameters, "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def library_parameters(component):
    """Only supplier-owned fields; never emit Pacage, core fields or UI state."""
    values = {"JLCPCB Part#": component["lcsc_id"], "LCSC URL": component["product_url"],
              "LCSC MPN": component["mpn"], "LCSC Manufacturer": component["manufacturer"],
              "LCSC Category": component["category"], "LCSC Description": component["description"],
              "LCSC Package": component["package"], "LCSC Datasheet URL": component["datasheet_url"],
              "LCSC Stock": component["stock"], "LCSC MOQ": component["moq"],
              "LCSC Requested Qty": component["requested_qty"], "LCSC Order Qty": component["order_qty"],
              "LCSC Currency": component["currency"]}
    values = {name: "" if value is None else str(value) for name, value in values.items()}
    for field, key in (("LCSC Unit Price", "unit_price"), ("LCSC Batch Cost", "batch_cost")):
        value = component[key]
        values[field] = "" if value is None else f"{format(Decimal(str(value)).normalize(), 'f')} {component['currency']}"
    return values


def check_target(snapshot, component):
    matches = [value for name, value in snapshot.get("parameters", {}).items() if name.casefold() == "mp"]
    if len(matches) != 1 or not isinstance(matches[0], str) or matches[0].strip().casefold() != component["mpn"].casefold():
        raise ValueError("symbol MP must exactly match the selected LCSC manufacturer part number")


class LcscClient:
    """The source toolkit's public-web search/detail endpoints, without caching."""

    def __init__(self, timeout=15.0, retries=1):
        self.timeout = timeout
        self.retries = retries

    def _request_result(self, method, path, *, query=None, body=None):
        url = BASE_URL + path
        if query:
            url += "?" + parse.urlencode(query)
        data = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "altium-mcp-lcsc/0.1", "Cookie": "currencyCode=USD"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(self.retries + 1):
            try:
                with request.urlopen(request.Request(url, data=data, headers=headers, method=method), timeout=self.timeout) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise LcscError("LCSC response is unexpectedly large")
                payload = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(payload, dict):
                    raise LcscError("LCSC response is not a JSON object")
                if payload.get("code") != 200:
                    raise LcscError(f"LCSC API error {payload.get('code')}: {clean_text(payload.get('msg'))}")
                if "result" not in payload:
                    raise LcscError("LCSC response schema changed: result is missing")
                return payload["result"]
            except error.HTTPError as exc:
                if exc.code not in {408, 500, 502, 503, 504} or attempt == self.retries:
                    raise LcscError(f"LCSC HTTP {exc.code}: {exc.reason}") from exc
            except (error.URLError, TimeoutError, OSError) as exc:
                if attempt == self.retries:
                    raise LcscError(f"LCSC request failed: {exc}") from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LcscError("LCSC returned invalid JSON; the endpoint may have changed") from exc
            time.sleep(min(2.0, 0.5 * (2 ** attempt)))

    def get_product(self, lcsc_id, qty=1):
        lcsc_id = validate_code(lcsc_id)
        validate_quantity(qty)
        payload = self._request_result("GET", "/product/detail", query={"productCode": lcsc_id})
        if not isinstance(payload, dict) or not payload.get("productCode"):
            raise LcscError(f"LCSC component {lcsc_id} was not found")
        component = component_from_payload(payload, qty)
        if component["lcsc_id"] != lcsc_id:
            raise LcscError("LCSC detail identity does not match the requested code")
        return component

    def lookup(self, query, qty=1, limit=5):
        validate_quantity(qty)
        if not isinstance(query, str) or not query.strip() or "\x00" in query or len(query) > 256:
            raise ValueError("query must be a nonempty string of at most 256 characters without NUL")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("limit must be an integer from 1 to 10")
        query = query.strip()
        if CODE.fullmatch(query):
            components = [self.get_product(query, qty)]
        else:
            result = self._request_result("POST", "/product/query/list", body={"keyword": query, "currentPage": 1, "pageSize": limit})
            if not isinstance(result, dict) or not isinstance(result.get("dataList"), list):
                raise LcscError("LCSC search response schema changed: dataList is missing")
            rows = [row for row in result["dataList"] if isinstance(row, dict)]
            exact = [row for row in rows if clean_text(row.get("productModel")).casefold() == query.casefold()]
            rows = exact or rows
            codes = list(dict.fromkeys(validate_code(row.get("productCode")) for row in rows))[:limit]
            components = [self.get_product(code, qty) for code in codes]
        for component in components:
            component["lcsc_parameters"] = library_parameters(component)
        return {"success": True, "query": query, "result_count": len(components), "components": components,
                "saved": False, "source": "LCSC web catalog"}
