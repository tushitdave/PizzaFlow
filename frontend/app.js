const API_BASE = "http://localhost:8000";

let menu = [];
let cart = [];

const byId = (id) => document.getElementById(id);
const money = (value) => `Rs. ${Number(value).toFixed(2)}`;

function menuItem(id) {
  return menu.find((item) => item.item_id === id);
}

function clearErrors() {
  [
    "nameError",
    "phoneError",
    "baseError",
    "pizzaError",
    "toppingError",
    "quantityError",
    "paymentError",
  ].forEach((id) => (byId(id).textContent = ""));
}

function fillSelect(id, items) {
  byId(id).innerHTML = items
    .map((item) => `<option value="${item.item_id}">${item.name} - ${money(item.price)}</option>`)
    .join("");
}

function calculateLocalBill() {
  const lines = cart.map((item) => {
    const base = menuItem(item.base_id);
    const pizza = menuItem(item.pizza_id);
    const topping = menuItem(item.topping_id);
    const unitPrice = base.price + pizza.price + topping.price;
    return { ...item, base, pizza, topping, unit_price: unitPrice, line_total: unitPrice * item.quantity };
  });

  const subtotal = lines.reduce((total, line) => total + line.line_total, 0);
  const totalQuantity = lines.reduce((total, line) => total + line.quantity, 0);
  const discount = totalQuantity >= 5 ? subtotal * 0.1 : 0;
  const gst = (subtotal - discount) * 0.18;
  return { lines, subtotal, discount, gst, finalTotal: subtotal - discount + gst };
}

function renderCart() {
  const bill = calculateLocalBill();

  byId("cartList").innerHTML =
    bill.lines.length === 0
      ? `<p class="note">No pizzas added yet.</p>`
      : bill.lines
          .map(
            (line, index) => `
              <div class="cart-item">
                <div class="cart-title">
                  <span>${line.pizza.name}</span>
                  <button class="remove" type="button" onclick="removeCartItem(${index})">Remove</button>
                </div>
                <p>${line.base.name} + ${line.topping.name}</p>
                <p>${money(line.unit_price)} x ${line.quantity} = <strong>${money(line.line_total)}</strong></p>
              </div>
            `
          )
          .join("");

  byId("subtotal").textContent = money(bill.subtotal);
  byId("discount").textContent = money(bill.discount);
  byId("gst").textContent = money(bill.gst);
  byId("finalTotal").textContent = money(bill.finalTotal);
}

window.removeCartItem = function removeCartItem(index) {
  cart = cart.filter((_, itemIndex) => itemIndex !== index);
  renderCart();
};

function validateDraft() {
  clearErrors();
  const quantityText = byId("quantityInput").value.trim();
  let valid = true;

  if (!/^\d+$/.test(quantityText) || Number(quantityText) < 1 || Number(quantityText) > 10) {
    byId("quantityError").textContent = "Quantity must be an integer from 1 to 10.";
    valid = false;
  }

  return valid;
}

function addPizza() {
  if (!validateDraft()) return;

  cart.push({
    base_id: byId("baseSelect").value,
    pizza_id: byId("pizzaSelect").value,
    topping_id: byId("toppingSelect").value,
    quantity: Number(byId("quantityInput").value),
  });

  renderCart();
}

async function parseSmartOrder() {
  byId("aiMessage").textContent = "Parsing order...";

  const response = await fetch(`${API_BASE}/parse-order`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: byId("smartInput").value }),
  });
  const data = await response.json();
  byId("aiMessage").textContent = data.ai_message || "No message returned.";

  if (data.success) {
    byId("baseSelect").value = data.base_id;
    byId("pizzaSelect").value = data.pizza_id;
    byId("toppingSelect").value = data.topping_id;
    byId("quantityInput").value = data.quantity;
    addPizza();
  }
}

function selectedPayment() {
  return document.querySelector('input[name="payment"]:checked')?.value || "";
}

async function submitOrder() {
  clearErrors();
  byId("submitMessage").textContent = "";

  if (cart.length === 0) {
    byId("submitMessage").textContent = "Add at least one pizza.";
    return;
  }

  const payload = {
    customer_name: byId("customerName").value,
    customer_phone: byId("customerPhone").value,
    payment_mode: selectedPayment(),
    cart_items: cart,
  };

  if (!payload.payment_mode) {
    byId("paymentError").textContent = "Select Cash, Card, or UPI.";
    return;
  }

  const response = await fetch(`${API_BASE}/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();

  if (!response.ok) {
    const errors = data.detail || {};
    byId("nameError").textContent = errors.customer_name || "";
    byId("phoneError").textContent = errors.customer_phone || "";
    byId("paymentError").textContent = errors.payment_mode || "";
    byId("submitMessage").textContent = "Fix the highlighted fields.";
    return;
  }

  cart = [];
  renderCart();
  const storage = data.supabase_saved ? "Saved to Supabase and local log." : "Saved to local log only.";
  byId("submitMessage").textContent = `Order ${data.order_id} confirmed. Final total: ${money(data.bill.final_total)} ${storage}`;
}

async function loadMenu() {
  try {
    const response = await fetch(`${API_BASE}/menu`);
    const data = await response.json();
    menu = data.items;
    fillSelect("baseSelect", data.bases);
    fillSelect("pizzaSelect", data.pizzas);
    fillSelect("toppingSelect", data.toppings);
    byId("apiStatus").textContent = "Backend: connected";
  } catch {
    byId("apiStatus").textContent = "Backend: offline";
  }
  renderCart();
}

byId("addButton").addEventListener("click", addPizza);
byId("parseButton").addEventListener("click", parseSmartOrder);
byId("submitButton").addEventListener("click", submitOrder);

loadMenu();
