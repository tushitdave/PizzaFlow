const API_BASE = "http://localhost:8000";

let adminToken = "";

const byId = (id) => document.getElementById(id);
const money = (value) => `Rs. ${Number(value || 0).toFixed(2)}`;

function authHeaders() {
  return { Authorization: `Bearer ${adminToken}` };
}

function dateQuery() {
  const params = new URLSearchParams();
  const start = byId("startDate").value;
  const end = byId("endDate").value;
  if (start) params.set("start_date", start);
  if (end) params.set("end_date", end);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function setDateRange(offsetDays) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const iso = date.toISOString().slice(0, 10);
  byId("startDate").value = iso;
  byId("endDate").value = iso;
  loadDashboard();
}

async function login() {
  byId("loginMessage").textContent = "Signing in...";
  const response = await fetch(`${API_BASE}/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: byId("adminPassword").value }),
  });
  const data = await response.json();

  if (!response.ok) {
    byId("loginMessage").textContent = data.detail || "Login failed.";
    return;
  }

  adminToken = data.token;
  byId("adminStatus").textContent = "Admin: signed in";
  byId("loginMessage").textContent = "Signed in.";
  loadDashboard();
}

async function loadDashboard() {
  if (!adminToken) {
    byId("loginMessage").textContent = "Sign in first.";
    return;
  }

  const response = await fetch(`${API_BASE}/admin/stats${dateQuery()}`, {
    headers: authHeaders(),
  });
  const data = await response.json();

  if (!response.ok) {
    byId("ordersBody").innerHTML = `<tr><td colspan="8">${data.detail || "Could not load dashboard."}</td></tr>`;
    return;
  }

  renderSummary(data.stats.summary);
  renderPaymentBreakdown(data.stats.payment_revenue);
  renderPopular("popularPizzas", data.stats.popular.pizzas);
  renderPopular("popularBases", data.stats.popular.bases);
  renderPopular("popularToppings", data.stats.popular.toppings);
  renderDiscounts(data.stats.discounted_orders);
  renderOrders(data.orders);
}

function renderSummary(summary) {
  byId("totalRevenue").textContent = money(summary.total_revenue);
  byId("totalOrders").textContent = summary.total_orders;
  byId("pizzasSold").textContent = summary.pizzas_sold;
  byId("totalDiscount").textContent = money(summary.total_discount);
  byId("totalGst").textContent = money(summary.total_gst);
}

function renderPaymentBreakdown(paymentRevenue) {
  const entries = Object.entries(paymentRevenue);
  const max = Math.max(...entries.map(([, value]) => Number(value)), 1);
  byId("paymentBreakdown").innerHTML = entries.length
    ? entries
        .map(([mode, value]) => barRow(mode, money(value), (Number(value) / max) * 100))
        .join("")
    : `<p class="note">No payment data.</p>`;
}

function renderPopular(containerId, rows) {
  const max = Math.max(...rows.map((row) => Number(row.quantity)), 1);
  byId(containerId).innerHTML = rows.length
    ? rows
        .map((row) => barRow(row.name, `${row.quantity} sold`, (Number(row.quantity) / max) * 100))
        .join("")
    : `<p class="note">No data yet.</p>`;
}

function barRow(label, value, width) {
  return `
    <div class="bar-row">
      <div class="bar-meta"><span>${label}</span><strong>${value}</strong></div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(width, 4)}%"></div></div>
    </div>
  `;
}

function renderDiscounts(discountedOrders) {
  if (!discountedOrders.length) {
    byId("discountBody").innerHTML = `<tr><td colspan="6">No discounted orders in this range.</td></tr>`;
    return;
  }

  byId("discountBody").innerHTML = discountedOrders
    .map(
      (order) => `
        <tr>
          <td>${new Date(order.created_at).toLocaleString()}</td>
          <td>${order.customer_name}</td>
          <td>${order.quantity}</td>
          <td>${money(order.subtotal)}</td>
          <td>${money(order.discount_amount)}</td>
          <td>${money(order.final_total)}</td>
        </tr>
      `
    )
    .join("");
}

function renderOrders(orders) {
  if (!orders.length) {
    byId("ordersBody").innerHTML = `<tr><td colspan="8">No orders found for this range.</td></tr>`;
    return;
  }

  byId("ordersBody").innerHTML = orders
    .map((order) => {
      const quantity = (order.order_line_items || []).reduce((total, line) => total + Number(line.quantity || 0), 0);
      return `
        <tr>
          <td>${new Date(order.created_at).toLocaleString()}</td>
          <td>${order.customer_name}</td>
          <td>${order.customer_phone}</td>
          <td>${quantity} pizza(s)</td>
          <td>${money(order.discount_amount)}</td>
          <td>${money(order.gst_amount)}</td>
          <td>${money(order.final_total)}</td>
          <td>${order.payment_mode}</td>
        </tr>
      `;
    })
    .join("");
}

byId("loginButton").addEventListener("click", login);
byId("refreshButton").addEventListener("click", loadDashboard);
byId("startDate").addEventListener("change", loadDashboard);
byId("endDate").addEventListener("change", loadDashboard);
byId("todayButton").addEventListener("click", () => setDateRange(0));
byId("yesterdayButton").addEventListener("click", () => setDateRange(-1));

