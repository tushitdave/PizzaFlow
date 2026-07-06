# PizzaFlow

Basic split frontend/backend implementation for the PizzaFlow assignment.

## Recommended Run

Start the Python backend:

```bash
python3 -m pip install -r backend/requirements.txt
python3 -m uvicorn backend.main:app --reload --port 8000
```

Start the static frontend:

```bash
cd frontend
python3 -m http.server 5500
```

Open:

- Customer app: `http://127.0.0.1:5500`
- Admin app: `http://127.0.0.1:5500/admin.html`
- Backend docs: `http://127.0.0.1:8000/docs`

## Backend Language

The separate backend is written in Python using FastAPI. It loads the menu from:

- `Data/types_of_bases.txt`
- `Data/types_of_pizzas.txt`
- `Data/types_of_toppings.txt`

Completed orders are appended to `orders_log.txt`.

Admin login is handled by the Python backend for this basic demo.

- Default admin password: `admin123`
- Override with `ADMIN_PASSWORD` in `.env`

## Supabase Setup

Run this file in Supabase SQL Editor:

```text
backend/supabase_schema.sql
```

The backend already has Supabase support:

- It reads/seeds `menu_items` from `Data/*.txt`.
- It saves completed orders to `orders`.
- It saves cart lines to `order_line_items`.
- It still writes `orders_log.txt` as a backup.

## Backend Deployment on Render

This repo includes `render.yaml` for the backend service.

Render settings:

- Service type: Web Service
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`

Environment variables required in Render:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL=openai/gpt-4o-mini`
- `ADMIN_PASSWORD`

After Render deploys the backend, update these files with the Render URL:

- `frontend/app.js`
- `frontend/admin.js`

Change:

```js
const API_BASE = "http://localhost:8000";
```

to:

```js
const API_BASE = "https://your-render-service.onrender.com";
```

## Assignment Coverage

- Runtime menu loading from text files.
- Name validation.
- Indian phone validation.
- Quantity validation from 1 to 10.
- Menu ID validation.
- Cash/Card/UPI payment validation.
- Unit price, subtotal, 10% discount for quantity >= 5, GST 18%, and final total.
- OpenRouter smart order endpoint using the key in `.env`.
- Admin login and latest-order dashboard.

## Demo Checklist

1. Manual order
   - Enter a valid name and phone.
   - Select base, pizza, topping, quantity, and payment.
   - Confirm the order.
   - Expected: order confirmation shows final total and Supabase save status.

2. Invalid input checks
   - Name: enter only spaces.
   - Phone: enter `1234567890`.
   - Quantity: enter `0`, `11`, or `2.5`.
   - Expected: clear validation errors, no crash.

3. Discount/GST check
   - Use quantity `5`.
   - Expected: 10% discount appears, then GST is calculated on post-discount amount.

4. Smart order
   - Type: `two thick crust farm house pizzas with extra cheese`.
   - Expected: AI/fallback maps it to menu IDs and adds it to the cart.

5. Admin dashboard
   - Open `admin.html`.
   - Password: `admin123`.
   - Expected: business dashboard and latest Supabase orders appear.
   - Review total revenue, total orders, pizzas sold, discount given, GST collected, payment breakdown, popular items, discounted orders, and recent orders.
   - Use Today, Yesterday, or custom date filters to compare revenue/order history.

The simpler split app lives in `backend/` and `frontend/`.
