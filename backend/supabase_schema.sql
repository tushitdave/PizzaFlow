create extension if not exists "pgcrypto";

create table if not exists public.menu_items (
  item_id text primary key,
  category text not null check (category in ('Base', 'Pizza', 'Topping')),
  name text not null,
  price integer not null check (price >= 0)
);

create table if not exists public.orders (
  order_id uuid primary key default gen_random_uuid(),
  customer_name text not null,
  customer_phone text not null,
  subtotal numeric(10, 2) not null,
  discount_amount numeric(10, 2) not null default 0,
  gst_amount numeric(10, 2) not null,
  final_total numeric(10, 2) not null,
  payment_mode text not null check (payment_mode in ('Cash', 'Card', 'UPI')),
  created_at timestamptz not null default now()
);

create table if not exists public.order_line_items (
  line_id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(order_id) on delete cascade,
  base_id text not null references public.menu_items(item_id),
  pizza_id text not null references public.menu_items(item_id),
  topping_id text not null references public.menu_items(item_id),
  quantity integer not null check (quantity between 1 and 10),
  unit_price integer not null check (unit_price >= 0),
  line_total integer not null check (line_total >= 0)
);

alter table public.menu_items enable row level security;
alter table public.orders enable row level security;
alter table public.order_line_items enable row level security;

drop policy if exists "menu readable" on public.menu_items;
create policy "menu readable"
  on public.menu_items for select
  using (true);

drop policy if exists "orders service role all" on public.orders;
create policy "orders service role all"
  on public.orders for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

drop policy if exists "line items service role all" on public.order_line_items;
create policy "line items service role all"
  on public.order_line_items for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

