from __future__ import annotations

import json
import os
import re
import secrets
import ssl
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "Data"
ORDERS_LOG = ROOT_DIR / "orders_log.txt"
ADMIN_SESSIONS: set[str] = set()
BUSINESS_TZ = timezone(timedelta(hours=5, minutes=30))

NAME_RE = re.compile(r"^[a-zA-Z\s]{2,40}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
PAYMENT_MODES = {"Cash", "Card", "UPI"}
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

Category = Literal["Base", "Pizza", "Topping"]


class MenuItem(BaseModel):
    item_id: str
    category: Category
    name: str
    price: int


class CartItem(BaseModel):
    base_id: str
    pizza_id: str
    topping_id: str
    quantity: int = Field(..., ge=1, le=10)


class OrderRequest(BaseModel):
    customer_name: str
    customer_phone: str
    payment_mode: Literal["Cash", "Card", "UPI"]
    cart_items: list[CartItem]


class ParseOrderRequest(BaseModel):
    input: str


class AdminLoginRequest(BaseModel):
    password: str


app = FastAPI(title="PizzaFlow Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()

    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return ""

    for line in env_file.read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in names:
            return value.strip().strip('"').strip("'")
    return ""


def admin_password() -> str:
    return read_env_value("ADMIN_PASSWORD") or "admin123"


def parse_menu_file(filename: str, category: Category) -> list[MenuItem]:
    path = DATA_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Missing menu file: {filename}")

    items: list[MenuItem] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split(";")]
        if len(parts) != 3:
            raise HTTPException(status_code=500, detail=f"Malformed menu line in {filename}:{line_number}")

        item_id, name, price_text = parts
        if not item_id or not name or not price_text.isdigit():
            raise HTTPException(status_code=500, detail=f"Invalid menu fields in {filename}:{line_number}")

        items.append(MenuItem(item_id=item_id, category=category, name=name, price=int(price_text)))

    if not items:
        raise HTTPException(status_code=500, detail=f"Menu file has no items: {filename}")
    return items


def load_menu() -> list[MenuItem]:
    return load_menu_from_files()


def load_menu_from_files() -> list[MenuItem]:
    return [
        *parse_menu_file("types_of_bases.txt", "Base"),
        *parse_menu_file("types_of_pizzas.txt", "Pizza"),
        *parse_menu_file("types_of_toppings.txt", "Topping"),
    ]


def get_supabase_config() -> tuple[str, str, str]:
    url = read_env_value("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    anon_key = read_env_value("SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY")
    service_key = read_env_value("SUPABASE_SERVICE_ROLE_KEY")
    return url, anon_key, service_key


def supabase_is_configured() -> bool:
    url, anon_key, service_key = get_supabase_config()
    return bool(url and anon_key and service_key)


def urlopen_json(request: urllib.request.Request, timeout: int = 20) -> object:
    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        if "CERTIFICATE_VERIFY_FAILED" not in str(error.reason):
            raise
        unverified_context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=unverified_context) as response:
            raw = response.read().decode("utf-8")

    if not raw:
        return None
    return json.loads(raw)


def supabase_request(path: str, method: str = "GET", body: Optional[object] = None, prefer: str = "") -> object:
    url, anon_key, service_key = get_supabase_config()
    if not url or not anon_key or not service_key:
        raise RuntimeError("Supabase is not configured.")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    request = urllib.request.Request(
        f"{url}/rest/v1/{path}",
        data=data,
        headers=headers,
        method=method,
    )
    return urlopen_json(request)


def seed_supabase_menu(menu: list[MenuItem]) -> None:
    supabase_request(
        "menu_items",
        method="POST",
        body=[item.model_dump() for item in menu],
        prefer="resolution=merge-duplicates",
    )


def load_menu_from_supabase() -> list[MenuItem]:
    response = supabase_request("menu_items?select=*&order=category.asc,item_id.asc")
    if not isinstance(response, list):
        return []
    return [MenuItem(**item) for item in response]


def load_menu_with_supabase() -> tuple[list[MenuItem], str]:
    file_menu = load_menu_from_files()
    if not supabase_is_configured():
        return file_menu, "files"

    try:
        supabase_menu = load_menu_from_supabase()
        if not supabase_menu:
            seed_supabase_menu(file_menu)
            supabase_menu = load_menu_from_supabase()
        return supabase_menu or file_menu, "supabase"
    except Exception:
        return file_menu, "files"


def menu_index(menu: list[MenuItem]) -> dict[str, MenuItem]:
    return {item.item_id: item for item in menu}


def validate_order(order: OrderRequest, menu: list[MenuItem]) -> None:
    errors: dict[str, str] = {}
    name = order.customer_name.strip()
    phone = order.customer_phone.strip()
    index = menu_index(menu)

    if not name:
        errors["customer_name"] = "Customer name is required."
    elif not NAME_RE.fullmatch(name):
        errors["customer_name"] = "Name must be 2-40 letters and spaces only."

    if not phone:
        errors["customer_phone"] = "Phone number is required."
    elif not PHONE_RE.fullmatch(phone):
        errors["customer_phone"] = "Phone must be 10 digits and start with 6, 7, 8, or 9."

    if order.payment_mode not in PAYMENT_MODES:
        errors["payment_mode"] = "Payment mode must be Cash, Card, or UPI."

    if not order.cart_items:
        errors["cart_items"] = "Add at least one pizza."

    for idx, item in enumerate(order.cart_items):
        base = index.get(item.base_id)
        pizza = index.get(item.pizza_id)
        topping = index.get(item.topping_id)

        if not base or base.category != "Base":
            errors[f"cart_items.{idx}.base_id"] = "Selected base is invalid."
        if not pizza or pizza.category != "Pizza":
            errors[f"cart_items.{idx}.pizza_id"] = "Selected pizza is invalid."
        if not topping or topping.category != "Topping":
            errors[f"cart_items.{idx}.topping_id"] = "Selected topping is invalid."
        if not isinstance(item.quantity, int) or item.quantity < 1 or item.quantity > 10:
            errors[f"cart_items.{idx}.quantity"] = "Quantity must be an integer from 1 to 10."

    if errors:
        raise HTTPException(status_code=400, detail=errors)


def calculate_bill(cart_items: list[CartItem], menu: list[MenuItem]) -> dict:
    index = menu_index(menu)
    lines = []

    for item in cart_items:
        base = index[item.base_id]
        pizza = index[item.pizza_id]
        topping = index[item.topping_id]
        unit_price = base.price + pizza.price + topping.price
        line_total = unit_price * item.quantity
        lines.append(
            {
                "base": base.model_dump(),
                "pizza": pizza.model_dump(),
                "topping": topping.model_dump(),
                "quantity": item.quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    subtotal = sum(line["line_total"] for line in lines)
    total_quantity = sum(line["quantity"] for line in lines)
    discount_amount = round(subtotal * 0.10, 2) if total_quantity >= 5 else 0
    gst_amount = round((subtotal - discount_amount) * 0.18, 2)
    final_total = round(subtotal - discount_amount + gst_amount, 2)

    return {
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "discount_amount": discount_amount,
        "gst_amount": gst_amount,
        "final_total": final_total,
    }


def append_order_log(order: OrderRequest, bill: dict, order_id: Optional[str] = None) -> str:
    order_id = order_id or f"ORD-{int(datetime.now(tz=timezone.utc).timestamp())}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"ORDER_ID: {order_id}",
        f"TIMESTAMP: {timestamp}",
        f"CUSTOMER_NAME: {order.customer_name.strip()}",
        f"CUSTOMER_PHONE: {order.customer_phone.strip()}",
        f"PAYMENT_MODE: {order.payment_mode}",
        "ITEMS:",
    ]

    for idx, line in enumerate(bill["lines"], start=1):
        lines.append(
            f"  {idx}. Base={line['base']['name']} ({line['base']['item_id']}) | "
            f"Pizza={line['pizza']['name']} ({line['pizza']['item_id']}) | "
            f"Topping={line['topping']['name']} ({line['topping']['item_id']}) | "
            f"Quantity={line['quantity']} | Unit={line['unit_price']} | LineTotal={line['line_total']}"
        )

    lines.extend(
        [
            f"SUBTOTAL: {bill['subtotal']}",
            f"DISCOUNT: {bill['discount_amount']}",
            f"GST_18_PERCENT: {bill['gst_amount']}",
            f"FINAL_TOTAL: {bill['final_total']}",
            "",
        ]
    )

    with ORDERS_LOG.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return order_id


def save_order_to_supabase(order: OrderRequest, bill: dict) -> str:
    created_order = supabase_request(
        "orders",
        method="POST",
        prefer="return=representation",
        body={
            "customer_name": order.customer_name.strip(),
            "customer_phone": order.customer_phone.strip(),
            "subtotal": bill["subtotal"],
            "discount_amount": bill["discount_amount"],
            "gst_amount": bill["gst_amount"],
            "final_total": bill["final_total"],
            "payment_mode": order.payment_mode,
        },
    )
    if not isinstance(created_order, list) or not created_order:
        raise RuntimeError("Supabase did not return the created order.")

    order_id = created_order[0]["order_id"]
    line_items = []
    for line in bill["lines"]:
        line_items.append(
            {
                "order_id": order_id,
                "base_id": line["base"]["item_id"],
                "pizza_id": line["pizza"]["item_id"],
                "topping_id": line["topping"]["item_id"],
                "quantity": line["quantity"],
                "unit_price": line["unit_price"],
                "line_total": line["line_total"],
            }
        )
    supabase_request("order_line_items", method="POST", body=line_items)
    return order_id


def list_orders_from_supabase(limit: int = 50) -> list[dict]:
    response = supabase_request(
        f"orders?select=*,order_line_items(*)&order=created_at.desc&limit={limit}"
    )
    if not isinstance(response, list):
        return []
    return response


def require_admin_token(authorization: Optional[str]) -> None:
    token = (authorization or "").replace("Bearer ", "", 1).strip()
    if not token or token not in ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="Admin login required.")


def parse_date_filter(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%d")
    if end_of_day:
        parsed = parsed + timedelta(days=1)
    return parsed.replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)


def parse_supabase_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def filter_orders_by_date(orders: list[dict], start_date: Optional[str], end_date: Optional[str]) -> list[dict]:
    start = parse_date_filter(start_date)
    end = parse_date_filter(end_date, end_of_day=True)
    filtered = []

    for order in orders:
        created = parse_supabase_time(order["created_at"])
        if start and created < start:
            continue
        if end and created >= end:
            continue
        filtered.append(order)
    return filtered


def summarize_orders(orders: list[dict], menu: list[MenuItem]) -> dict:
    menu_by_id = menu_index(menu)
    total_orders = len(orders)
    total_revenue = round(sum(float(order.get("final_total") or 0) for order in orders), 2)
    total_discount = round(sum(float(order.get("discount_amount") or 0) for order in orders), 2)
    total_gst = round(sum(float(order.get("gst_amount") or 0) for order in orders), 2)
    total_subtotal = round(sum(float(order.get("subtotal") or 0) for order in orders), 2)

    pizzas_sold = 0
    payment_revenue: dict[str, float] = defaultdict(float)
    pizza_counter: Counter[str] = Counter()
    base_counter: Counter[str] = Counter()
    topping_counter: Counter[str] = Counter()

    for order in orders:
        payment_revenue[str(order.get("payment_mode") or "Unknown")] += float(order.get("final_total") or 0)
        for line in order.get("order_line_items") or []:
            quantity = int(line.get("quantity") or 0)
            pizzas_sold += quantity
            pizza_counter[str(line.get("pizza_id"))] += quantity
            base_counter[str(line.get("base_id"))] += quantity
            topping_counter[str(line.get("topping_id"))] += quantity

    def counter_to_rows(counter: Counter[str]) -> list[dict]:
        rows = []
        for item_id, quantity in counter.most_common(5):
            item = menu_by_id.get(item_id)
            rows.append(
                {
                    "item_id": item_id,
                    "name": item.name if item else item_id,
                    "quantity": quantity,
                }
            )
        return rows

    discounted_orders = [
        {
            "order_id": order["order_id"],
            "created_at": order["created_at"],
            "customer_name": order["customer_name"],
            "quantity": sum(int(line.get("quantity") or 0) for line in order.get("order_line_items") or []),
            "subtotal": float(order.get("subtotal") or 0),
            "discount_amount": float(order.get("discount_amount") or 0),
            "final_total": float(order.get("final_total") or 0),
        }
        for order in orders
        if float(order.get("discount_amount") or 0) > 0
    ]

    return {
        "summary": {
            "total_orders": total_orders,
            "pizzas_sold": pizzas_sold,
            "total_subtotal": total_subtotal,
            "total_revenue": total_revenue,
            "total_discount": total_discount,
            "total_gst": total_gst,
        },
        "payment_revenue": {key: round(value, 2) for key, value in payment_revenue.items()},
        "popular": {
            "pizzas": counter_to_rows(pizza_counter),
            "bases": counter_to_rows(base_counter),
            "toppings": counter_to_rows(topping_counter),
        },
        "discounted_orders": discounted_orders[:20],
    }


def openrouter_parse_order(text: str, menu: list[MenuItem]) -> dict:
    api_key = read_env_value("OPENROUTER_API_KEY", "open_router_api")
    if not api_key:
        return {"success": False, "ai_message": "OpenRouter key is not configured."}

    model = read_env_value("OPENROUTER_MODEL") or "openai/gpt-4o-mini"
    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a pizza ordering assistant. Match the user's natural language request "
                    "to the provided menu data. Output STRICT JSON only. For successful orders return "
                    '{"success":true,"base_id":"B1","pizza_id":"P1","topping_id":"T1","quantity":1,'
                    '"ai_message":"short confirmation"}. If unclear return '
                    '{"success":false,"ai_message":"short reason"}. Choose only IDs from the menu. '
                    "Number words such as one, two, three, four, and five are valid quantities. "
                    "Example: 'two thick crust farm house pizzas with extra cheese' means quantity 2."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"menu": [item.model_dump() for item in menu], "user_input": text}),
            },
        ],
    }

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "PizzaFlow",
        },
        method="POST",
    )

    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            return json.loads(content)
    except urllib.error.URLError as error:
        reason = str(error.reason)
        if "CERTIFICATE_VERIFY_FAILED" not in reason:
            return {"success": False, "ai_message": f"AI network error: {error.reason}"}

        try:
            unverified_context = ssl._create_unverified_context()
            with urllib.request.urlopen(request, timeout=20, context=unverified_context) as response:
                body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                return json.loads(content)
        except urllib.error.HTTPError as fallback_error:
            detail = fallback_error.read().decode("utf-8", errors="ignore")
            message = "OpenRouter request failed."
            try:
                parsed_error = json.loads(detail)
                message = parsed_error.get("error", {}).get("message") or parsed_error.get("message") or message
            except json.JSONDecodeError:
                if detail:
                    message = detail[:180]
            return {"success": False, "ai_message": f"AI error: {message}"}
        except Exception:
            return {"success": False, "ai_message": "AI SSL certificate issue. Use dropdowns or install Python certificates."}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        message = "OpenRouter request failed."
        try:
            parsed_error = json.loads(detail)
            message = parsed_error.get("error", {}).get("message") or parsed_error.get("message") or message
        except json.JSONDecodeError:
            if detail:
                message = detail[:180]
        return {"success": False, "ai_message": f"AI error: {message}"}
    except (KeyError, json.JSONDecodeError, TimeoutError):
        return {"success": False, "ai_message": "AI returned an unreadable response. Please use dropdowns."}


def fallback_parse_order(text: str, menu: list[MenuItem]) -> dict:
    normalized = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()

    quantity = 1
    digit_match = re.search(r"\b(10|[1-9])\b", normalized)
    if digit_match:
        quantity = int(digit_match.group(1))
    else:
        for word, value in NUMBER_WORDS.items():
            if re.search(rf"\b{word}\b", normalized):
                quantity = value
                break

    def find_item(category: Category) -> Optional[MenuItem]:
        choices = [item for item in menu if item.category == category]
        for item in sorted(choices, key=lambda option: len(option.name), reverse=True):
            name = item.name.lower().replace("-", " ")
            words = [word for word in re.split(r"\s+", name) if word]
            if all(word in normalized for word in words):
                return item
        return None

    base = find_item("Base")
    pizza = find_item("Pizza")
    topping = find_item("Topping")

    if not base or not pizza or not topping or quantity < 1 or quantity > 10:
        return {"success": False, "ai_message": "I could not map that text to base, pizza, topping, and quantity."}

    return {
        "success": True,
        "base_id": base.item_id,
        "pizza_id": pizza.item_id,
        "topping_id": topping.item_id,
        "quantity": quantity,
        "ai_message": f"Matched {quantity} {pizza.name} pizza(s) with {base.name} and {topping.name}.",
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "supabase_configured": supabase_is_configured()}


@app.get("/menu")
def get_menu() -> dict:
    menu, source = load_menu_with_supabase()
    return {
        "source": source,
        "items": [item.model_dump() for item in menu],
        "bases": [item.model_dump() for item in menu if item.category == "Base"],
        "pizzas": [item.model_dump() for item in menu if item.category == "Pizza"],
        "toppings": [item.model_dump() for item in menu if item.category == "Topping"],
    }


@app.post("/orders")
def create_order(order: OrderRequest) -> dict:
    menu, menu_source = load_menu_with_supabase()
    validate_order(order, menu)
    bill = calculate_bill(order.cart_items, menu)
    supabase_saved = False
    supabase_error = ""
    order_id = ""

    if supabase_is_configured():
        try:
            order_id = save_order_to_supabase(order, bill)
            supabase_saved = True
        except Exception as error:
            supabase_error = str(error)

    order_id = append_order_log(order, bill, order_id or None)
    return {
        "success": True,
        "order_id": order_id,
        "bill": bill,
        "menu_source": menu_source,
        "supabase_saved": supabase_saved,
        "supabase_error": supabase_error,
    }


@app.post("/parse-order")
def parse_order(request: ParseOrderRequest) -> dict:
    text = request.input.strip()
    if not text:
        return {"success": False, "ai_message": "Type a pizza order first."}

    menu, _source = load_menu_with_supabase()
    parsed = openrouter_parse_order(text, menu)
    if not parsed.get("success"):
        fallback = fallback_parse_order(text, menu)
        if fallback.get("success"):
            return fallback
        return parsed

    try:
        item = CartItem(
            base_id=str(parsed["base_id"]),
            pizza_id=str(parsed["pizza_id"]),
            topping_id=str(parsed["topping_id"]),
            quantity=int(parsed["quantity"]),
        )
        validate_order(
            OrderRequest(
                customer_name="Test User",
                customer_phone="9876543210",
                payment_mode="UPI",
                cart_items=[item],
            ),
            menu,
        )
    except Exception:
        return {"success": False, "ai_message": "AI returned a menu item that is not valid."}

    return parsed


@app.post("/admin/login")
def admin_login(request: AdminLoginRequest) -> dict:
    if request.password != admin_password():
        raise HTTPException(status_code=401, detail="Invalid admin password.")

    token = secrets.token_urlsafe(32)
    ADMIN_SESSIONS.add(token)
    return {"success": True, "token": token}


@app.get("/admin/orders")
def admin_orders(authorization: Optional[str] = Header(default=None)) -> dict:
    require_admin_token(authorization)
    if not supabase_is_configured():
        return {"success": True, "source": "none", "orders": []}

    try:
        return {"success": True, "source": "supabase", "orders": list_orders_from_supabase()}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Could not load Supabase orders: {error}")


@app.get("/admin/stats")
def admin_stats(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    require_admin_token(authorization)
    if not supabase_is_configured():
        return {
            "success": True,
            "source": "none",
            "range": {"start_date": start_date, "end_date": end_date},
            "stats": summarize_orders([], load_menu_from_files()),
            "orders": [],
        }

    try:
        menu, menu_source = load_menu_with_supabase()
        orders = filter_orders_by_date(list_orders_from_supabase(limit=1000), start_date, end_date)
        return {
            "success": True,
            "source": "supabase",
            "menu_source": menu_source,
            "range": {"start_date": start_date, "end_date": end_date},
            "stats": summarize_orders(orders, menu),
            "orders": orders[:50],
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must use YYYY-MM-DD format.")
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Could not load dashboard stats: {error}")
