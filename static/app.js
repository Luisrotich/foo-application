document.addEventListener('DOMContentLoaded', () => {
    // -------------------- DOM refs (customer) --------------------
    const splash = document.getElementById('splash');
    const app = document.getElementById('app');
    const getStartedBtn = document.getElementById('getStartedBtn');

    const productGrid = document.getElementById('productGrid');
    const searchInput = document.getElementById('searchInput');
    const categoryGrid = document.getElementById('categoryGrid');
    const cartBadge = document.getElementById('cartBadge');
    const cartBtn = document.getElementById('cartBtn');
    const cartView = document.getElementById('cartView');
    const cartList = document.getElementById('cartList');
    const cartTotalPrice = document.getElementById('cartTotalPrice');
    const cartBack = document.getElementById('cartBack');
    const checkoutBtn = document.getElementById('checkoutBtn');
    const viewAllBtn = document.getElementById('viewAllBtn');

    // Product modal
    const modal = document.getElementById('productModal');
    const modalClose = document.getElementById('modalClose');
    const modalImage = document.getElementById('modalImage');
    const modalName = document.getElementById('modalName');
    const modalPrice = document.getElementById('modalPrice');
    const modalDesc = document.getElementById('modalDesc');
    const modalStock = document.getElementById('modalStock');
    const qtyNum = document.getElementById('qtyNum');
    const qtyMinus = document.getElementById('qtyMinus');
    const qtyPlus = document.getElementById('qtyPlus');
    const modalAdd = document.getElementById('modalAdd');

    // M-PESA modal
    const mpesaModal = document.getElementById('mpesaModal');
    const mpesaClose = document.getElementById('mpesaClose');
    const mpesaTotal = document.getElementById('mpesaTotal');
    const mpesaItemCount = document.getElementById('mpesaItemCount');
    const mpesaPhone = document.getElementById('mpesaPhone');
    const mpesaPayBtn = document.getElementById('mpesaPayBtn');
    const mpesaStatus = document.getElementById('mpesaStatus');

    // Install popup
    const installPopup = document.getElementById('installPopup');
    const installBtn = document.getElementById('installBtn');
    const installLater = document.getElementById('installLater');

    const toast = document.getElementById('toast');

    // -------------------- State --------------------
    let products = [];
    let currentProductId = null;
    let cart = JSON.parse(localStorage.getItem('cart')) || [];

    // -------------------- Helpers --------------------
    function showToast(msg) {
        toast.textContent = msg;
        toast.classList.remove('hidden');
        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => toast.classList.add('hidden'), 3000);
    }

    function updateBadge() {
        const total = cart.reduce((sum, item) => sum + item.qty, 0);
        cartBadge.textContent = total;
    }

    function saveCart() {
        localStorage.setItem('cart', JSON.stringify(cart));
        updateBadge();
    }

    function getImageSrc(product) {
        return product.image ? `/static/uploads/${product.image}` : null;
    }

    // -------------------- Render products --------------------
    function renderProducts(productList) {
        if (!productList.length) {
            productGrid.innerHTML = '<p style="grid-column:1/-1; text-align:center; color:#888;">No products found</p>';
            return;
        }
        productGrid.innerHTML = productList.map(p => {
            const imgSrc = getImageSrc(p);
            return `
                <div class="product-card" data-id="${p.id}">
                    <button class="fav ${isFav(p.id) ? 'active' : ''}" data-id="${p.id}"><i class="fas fa-heart"></i></button>
                    ${imgSrc ? `<img src="${imgSrc}" alt="${p.name}" loading="lazy" />` : `<span class="icon"><i class="fas ${p.image_icon || 'fa-apple-alt'}"></i></span>`}
                    <div class="name">${p.name}</div>
                    <div class="weight">${p.stock > 0 ? 'In stock' : 'Out of stock'}</div>
                    <div class="price-rating">
                        <span class="price">$${p.price.toFixed(2)}</span>
                    </div>
                    <div class="delivery">${p.delivery || 'Delivered'}</div>
                </div>
            `;
        }).join('');

        document.querySelectorAll('.product-card').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.closest('.fav')) return;
                const id = parseInt(card.dataset.id);
                const prod = products.find(p => p.id === id);
                if (prod) openModal(prod);
            });
        });

        document.querySelectorAll('.fav').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = parseInt(btn.dataset.id);
                toggleFav(id);
                btn.classList.toggle('active');
            });
        });
    }

    function isFav(id) {
        const favs = JSON.parse(localStorage.getItem('favorites') || '[]');
        return favs.includes(id);
    }

    function toggleFav(id) {
        let favs = JSON.parse(localStorage.getItem('favorites') || '[]');
        if (favs.includes(id)) {
            favs = favs.filter(f => f !== id);
        } else {
            favs.push(id);
        }
        localStorage.setItem('favorites', JSON.stringify(favs));
    }

    // -------------------- Modal --------------------
    function openModal(product) {
        currentProductId = product.id;
        const imgSrc = getImageSrc(product);
        modalImage.innerHTML = imgSrc ? `<img src="${imgSrc}" alt="${product.name}" />` : `<i class="fas ${product.image_icon || 'fa-apple-alt'}"></i>`;
        modalName.textContent = product.name;
        modalPrice.textContent = `$${product.price.toFixed(2)}`;
        modalDesc.textContent = product.description || 'Fresh and delicious.';
        modalStock.textContent = `In stock: ${product.stock || 0}`;
        qtyNum.textContent = 1;
        modalAdd.disabled = (product.stock || 0) <= 0;
        modal.classList.add('open');
    }

    function closeModal() {
        modal.classList.remove('open');
    }

    modalClose.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    qtyMinus.addEventListener('click', () => {
        let val = parseInt(qtyNum.textContent);
        if (val > 1) qtyNum.textContent = val - 1;
    });
    qtyPlus.addEventListener('click', () => {
        let val = parseInt(qtyNum.textContent);
        const product = products.find(p => p.id === currentProductId);
        if (product && val < (product.stock || 0)) qtyNum.textContent = val + 1;
        else showToast('Not enough stock');
    });

    modalAdd.addEventListener('click', () => {
        if (currentProductId === null) return;
        const qty = parseInt(qtyNum.textContent);
        const product = products.find(p => p.id === currentProductId);
        if (!product) return;
        if (product.stock < qty) {
            showToast('Not enough stock');
            return;
        }
        const existing = cart.find(item => item.id === product.id);
        if (existing) {
            existing.qty += qty;
        } else {
            cart.push({ ...product, qty });
        }
        saveCart();
        closeModal();
        showToast(`Added ${qty} × ${product.name} to cart`);
    });

    // -------------------- Category & Search --------------------
    let activeCategory = null;

    categoryGrid.addEventListener('click', (e) => {
        const item = e.target.closest('.category-item');
        if (!item) return;
        const cat = item.dataset.cat;
        document.querySelectorAll('.category-item').forEach(el => el.classList.remove('active'));
        if (activeCategory === cat) {
            activeCategory = null;
        } else {
            item.classList.add('active');
            activeCategory = cat;
        }
        applyFilters();
    });

    searchInput.addEventListener('input', applyFilters);

    function applyFilters() {
        const query = searchInput.value.toLowerCase().trim();
        let filtered = products;
        if (activeCategory) {
            filtered = filtered.filter(p => p.category === activeCategory);
        }
        if (query) {
            filtered = filtered.filter(p => p.name.toLowerCase().includes(query));
        }
        renderProducts(filtered);
    }

    viewAllBtn.addEventListener('click', () => {
        activeCategory = null;
        document.querySelectorAll('.category-item').forEach(el => el.classList.remove('active'));
        searchInput.value = '';
        renderProducts(products);
    });

    // -------------------- Cart UI --------------------
    function renderCart() {
        if (cart.length === 0) {
            cartList.innerHTML = '<p style="text-align:center;color:#888;margin-top:2rem;">Your cart is empty</p>';
            cartTotalPrice.textContent = '$0.00';
            return;
        }
        let html = '';
        let total = 0;
        cart.forEach((item, index) => {
            const subtotal = item.price * item.qty;
            total += subtotal;
            const imgSrc = getImageSrc(item);
            html += `
                <div class="cart-item" data-index="${index}">
                    ${imgSrc ? `<img src="${imgSrc}" alt="${item.name}" />` : `<span class="icon"><i class="fas ${item.image_icon || 'fa-apple-alt'}"></i></span>`}
                    <div class="info">
                        <div class="name">${item.name}</div>
                        <div class="price">$${item.price.toFixed(2)}</div>
                    </div>
                    <div class="qty-control">
                        <button class="cart-qty-minus" data-index="${index}"><i class="fas fa-minus"></i></button>
                        <span>${item.qty}</span>
                        <button class="cart-qty-plus" data-index="${index}"><i class="fas fa-plus"></i></button>
                    </div>
                    <button class="remove" data-index="${index}"><i class="fas fa-trash"></i></button>
                </div>
            `;
        });
        cartList.innerHTML = html;
        cartTotalPrice.textContent = `$${total.toFixed(2)}`;

        document.querySelectorAll('.cart-qty-minus').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(btn.dataset.index);
                if (cart[idx].qty > 1) {
                    cart[idx].qty--;
                } else {
                    cart.splice(idx, 1);
                }
                saveCart();
                renderCart();
            });
        });
        document.querySelectorAll('.cart-qty-plus').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(btn.dataset.index);
                const product = products.find(p => p.id === cart[idx].id);
                if (product && cart[idx].qty < product.stock) {
                    cart[idx].qty++;
                } else {
                    showToast('Not enough stock');
                }
                saveCart();
                renderCart();
            });
        });
        document.querySelectorAll('.remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(btn.dataset.index);
                cart.splice(idx, 1);
                saveCart();
                renderCart();
            });
        });
    }

    // -------------------- Navigation --------------------
    function showHome() {
        cartView.classList.add('hidden');
        app.classList.remove('hidden');
        document.querySelector('.bottom-nav .nav-item[data-view="home"]')?.classList.add('active');
        document.querySelector('.bottom-nav .nav-item[data-view="cart"]')?.classList.remove('active');
        document.querySelector('.bottom-nav .nav-item[data-view="admin"]')?.classList.remove('active');
    }

    function showCartView() {
        app.classList.add('hidden');
        cartView.classList.remove('hidden');
        renderCart();
        document.querySelector('.bottom-nav .nav-item[data-view="cart"]')?.classList.add('active');
        document.querySelector('.bottom-nav .nav-item[data-view="home"]')?.classList.remove('active');
        document.querySelector('.bottom-nav .nav-item[data-view="admin"]')?.classList.remove('active');
    }

    function goToAdmin() {
        window.location.href = '/admin';
    }

    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            if (view === 'home') showHome();
            else if (view === 'cart') showCartView();
            else if (view === 'admin') goToAdmin();
        });
    });

    cartBtn.addEventListener('click', showCartView);
    cartBack.addEventListener('click', showHome);

    // -------------------- M-PESA Checkout --------------------
    checkoutBtn.addEventListener('click', () => {
        if (cart.length === 0) {
            showToast('Cart is empty');
            return;
        }
        const total = cart.reduce((sum, item) => sum + item.price * item.qty, 0);
        mpesaTotal.textContent = total.toFixed(2);
        mpesaItemCount.textContent = cart.reduce((s, i) => s + i.qty, 0);
        mpesaPhone.value = '';
        mpesaStatus.innerHTML = '';
        mpesaModal.classList.add('open');
    });

    mpesaClose.addEventListener('click', () => mpesaModal.classList.remove('open'));
    mpesaModal.addEventListener('click', (e) => {
        if (e.target === mpesaModal) mpesaModal.classList.remove('open');
    });

    mpesaPayBtn.addEventListener('click', async () => {
        const phone = mpesaPhone.value.trim();
        if (!phone || phone.length < 10) {
            mpesaStatus.innerHTML = '<span style="color: #e74c3c;"><i class="fas fa-exclamation-circle"></i> Enter a valid phone (e.g., 2547XXXXXXXX)</span>';
            return;
        }
        const total = parseFloat(mpesaTotal.textContent);
        mpesaPayBtn.disabled = true;
        mpesaStatus.innerHTML = '<div class="spinner"></div> Processing payment...';
        try {
            const res = await fetch('/api/checkout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: cart, total, phone })
            });
            const data = await res.json();
            if (data.status === 'order_placed') {
                mpesaStatus.innerHTML = '<span style="color: #27ae60;"><i class="fas fa-check-circle"></i> Payment initiated! Order placed.</span>';
                cart = [];
                saveCart();
                renderCart();
                setTimeout(() => {
                    mpesaModal.classList.remove('open');
                    showHome();
                }, 2000);
            } else {
                mpesaStatus.innerHTML = '<span style="color: #e74c3c;"><i class="fas fa-times-circle"></i> Error placing order.</span>';
            }
        } catch (e) {
            mpesaStatus.innerHTML = '<span style="color: #e74c3c;"><i class="fas fa-times-circle"></i> Network error.</span>';
        } finally {
            mpesaPayBtn.disabled = false;
        }
    });

    // -------------------- Load products --------------------
    async function loadProducts() {
        try {
            const res = await fetch('/api/products');
            products = await res.json();
            renderProducts(products);
            updateBadge();
            showHome();
        } catch (e) {
            showToast('Failed to load products');
        }
    }

    // -------------------- PWA Install --------------------
    let deferredPrompt;
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        installPopup.classList.remove('hidden');
    });

    installBtn.addEventListener('click', async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const result = await deferredPrompt.userChoice;
            if (result.outcome === 'accepted') {
                showToast('App installed!');
            } else {
                showToast('Installation declined');
            }
            deferredPrompt = null;
            installPopup.classList.add('hidden');
        }
    });

    installLater.addEventListener('click', () => {
        installPopup.classList.add('hidden');
    });

    // -------------------- Splash transition --------------------
    getStartedBtn.addEventListener('click', () => {
        splash.classList.add('hidden');
        loadProducts();
    });

    // ============================================================
    //  ADMIN SECTION – runs if we are on the admin page
    //  (detects .admin-wrapper as used in the HTML)
    // ============================================================
    if (document.querySelector('.admin-wrapper')) {
        initAdmin();
    }

    function initAdmin() {
        // ----- Sidebar toggle (mobile) -----
        const sidebar = document.getElementById('adminSidebar');
        const toggleBtn = document.getElementById('sidebarToggle');
        const overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        document.body.appendChild(overlay);

        toggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
            overlay.classList.toggle('active');
        });
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
        });

        // ----- Sidebar navigation links -----
        document.querySelectorAll('.sidebar-link[data-section]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const section = link.dataset.section;
                // Update active link
                document.querySelectorAll('.sidebar-link[data-section]').forEach(l => l.classList.remove('active'));
                link.classList.add('active');
                // Show corresponding section
                document.querySelectorAll('.admin-section').forEach(el => el.classList.remove('active'));
                document.getElementById(`section-${section}`).classList.add('active');
                // Close sidebar on mobile
                sidebar.classList.remove('open');
                overlay.classList.remove('active');
            });
        });

        // ----- Clock -----
        function updateClock() {
            const now = new Date();
            const timeEl = document.getElementById('adminTime');
            if (timeEl) timeEl.textContent = now.toLocaleString();
        }
        updateClock();
        setInterval(updateClock, 1000);

        // ----- Load data -----
        loadStats();
        loadProductsAdmin();
        loadOrders();
        loadPayments();

        // ----- Product form modal -----
        const formModal = document.getElementById('productFormModal');
        const form = document.getElementById('productForm');
        const editId = document.getElementById('editId');
        const closeFormBtn = document.getElementById('closeFormBtn');

        document.getElementById('addProductBtn').addEventListener('click', () => openProductForm());
        closeFormBtn.addEventListener('click', () => formModal.classList.remove('open'));
        formModal.addEventListener('click', (e) => {
            if (e.target === formModal) formModal.classList.remove('open');
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = editId.value;
            const formData = new FormData();
            formData.append('name', document.getElementById('pName').value);
            formData.append('price', document.getElementById('pPrice').value);
            formData.append('description', document.getElementById('pDesc').value);
            formData.append('category', document.getElementById('pCategory').value);
            formData.append('image_icon', document.getElementById('pIcon').value);
            formData.append('rating', document.getElementById('pRating').value);
            formData.append('delivery', document.getElementById('pDelivery').value);
            formData.append('stock', document.getElementById('pStock').value);
            formData.append('available', document.getElementById('pAvailable').checked ? 1 : 0);

            const fileInput = document.getElementById('pImage');
            let imageFilename = null;
            if (fileInput.files.length > 0) {
                const file = fileInput.files[0];
                const uploadData = new FormData();
                uploadData.append('image', file);
                const uploadRes = await fetch('/api/upload', {
                    method: 'POST',
                    body: uploadData
                });
                const uploadJson = await uploadRes.json();
                if (uploadJson.filename) {
                    imageFilename = uploadJson.filename;
                } else {
                    showToast('Image upload failed');
                    return;
                }
            }

            // Build JSON payload
            const payload = {
                name: formData.get('name'),
                price: parseFloat(formData.get('price')),
                description: formData.get('description'),
                category: formData.get('category'),
                image_icon: formData.get('image_icon'),
                rating: parseFloat(formData.get('rating')),
                delivery: formData.get('delivery'),
                stock: parseInt(formData.get('stock')),
                available: parseInt(formData.get('available')),
            };
            if (imageFilename) payload.image = imageFilename;

            const url = id ? `/api/products/${id}` : '/api/products';
            const method = id ? 'PUT' : 'POST';
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                formModal.classList.remove('open');
                loadProductsAdmin();
                loadStats();
                showToast(id ? 'Product updated' : 'Product added');
            } else {
                showToast('Error saving product');
            }
        });

        function openProductForm(product = null) {
            document.getElementById('formTitle').textContent = product ? 'Edit Product' : 'Add Product';
            editId.value = product ? product.id : '';
            document.getElementById('pName').value = product ? product.name : '';
            document.getElementById('pPrice').value = product ? product.price : '';
            document.getElementById('pDesc').value = product ? product.description : '';
            document.getElementById('pCategory').value = product ? product.category : 'Fruits';
            document.getElementById('pIcon').value = product ? product.image_icon : 'fa-apple-alt';
            document.getElementById('pRating').value = product ? product.rating : 4.0;
            document.getElementById('pDelivery').value = product ? product.delivery : '';
            document.getElementById('pStock').value = product ? product.stock : 0;
            document.getElementById('pAvailable').checked = product ? product.available == 1 : true;
            document.getElementById('currentImagePreview').innerHTML = product && product.image ? 
                `<img src="/static/uploads/${product.image}" style="max-width:100px; border-radius:8px;" />` : '';
            document.getElementById('pImage').value = '';
            formModal.classList.add('open');
        }

        // ----- Edit/Delete product events (delegation) -----
        document.getElementById('productTableBody').addEventListener('click', async (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const id = btn.dataset.id;
            if (btn.classList.contains('edit-product')) {
                const product = await fetch(`/api/products`).then(r => r.json()).then(data => data.find(p => p.id == id));
                if (product) openProductForm(product);
            } else if (btn.classList.contains('delete-product')) {
                if (confirm('Delete this product?')) {
                    await fetch(`/api/products/${id}`, { method: 'DELETE' });
                    loadProductsAdmin();
                    loadStats();
                    showToast('Product deleted');
                }
            }
        });

        // ----- Order status update -----
        document.getElementById('orderTableBody').addEventListener('change', async (e) => {
            if (e.target.classList.contains('order-status')) {
                const id = e.target.dataset.id;
                const status = e.target.value;
                await fetch(`/api/orders/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status })
                });
                loadOrders();
                loadStats();
                showToast('Order status updated');
            }
        });

        // ----- API calls -----
        async function loadStats() {
            const res = await fetch('/api/stats');
            const stats = await res.json();
            document.getElementById('statProducts').textContent = stats.total_products;
            document.getElementById('statOrders').textContent = stats.total_orders;
            document.getElementById('statRevenue').textContent = `$${stats.total_revenue.toFixed(2)}`;
            document.getElementById('statPending').textContent = stats.pending_orders;
            updateCharts(stats);
        }

        let revenueChart, statusChart;
        function updateCharts(stats) {
            const ctx1 = document.getElementById('revenueChart').getContext('2d');
            const ctx2 = document.getElementById('statusChart').getContext('2d');
            if (revenueChart) revenueChart.destroy();
            if (statusChart) statusChart.destroy();
            // Dummy weekly data – replace with real data in production
            revenueChart = new Chart(ctx1, {
                type: 'bar',
                data: {
                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                    datasets: [{
                        label: 'Revenue ($)',
                        data: [50, 80, 120, 90, 150, 200, 180],
                        backgroundColor: '#F97316'
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
            statusChart = new Chart(ctx2, {
                type: 'pie',
                data: {
                    labels: ['Pending', 'Paid', 'Shipped', 'Delivered'],
                    datasets: [{
                        data: [stats.pending_orders, 5, 3, 7],
                        backgroundColor: ['#f39c12', '#3498db', '#2ecc71', '#27ae60']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }

        async function loadProductsAdmin() {
            const res = await fetch('/api/products');
            const data = await res.json();
            const tbody = document.getElementById('productTableBody');
            tbody.innerHTML = data.map(p => `
                <tr>
                    <td>${p.id}</td>
                    <td>${p.image ? `<img src="/static/uploads/${p.image}" />` : `<i class="fas ${p.image_icon || 'fa-apple-alt'}"></i>`}</td>
                    <td>${p.name}</td>
                    <td>$${p.price.toFixed(2)}</td>
                    <td>${p.stock}</td>
                    <td>${p.available ? '✅' : '❌'}</td>
                    <td>
                        <button class="admin-btn small edit-product" data-id="${p.id}"><i class="fas fa-edit"></i></button>
                        <button class="admin-btn small danger delete-product" data-id="${p.id}"><i class="fas fa-trash"></i></button>
                    </td>
                </tr>
            `).join('');
        }

        async function loadOrders() {
            const res = await fetch('/api/orders');
            const data = await res.json();
            const tbody = document.getElementById('orderTableBody');
            tbody.innerHTML = data.map(o => `
                <tr>
                    <td>#${o.id}</td>
                    <td>${JSON.parse(o.items).map(i => `${i.name} x${i.qty}`).join(', ')}</td>
                    <td>$${o.total.toFixed(2)}</td>
                    <td>${o.phone || 'N/A'}</td>
                    <td>
                        <select class="order-status" data-id="${o.id}">
                            <option value="pending" ${o.status === 'pending' ? 'selected' : ''}>Pending</option>
                            <option value="paid" ${o.status === 'paid' ? 'selected' : ''}>Paid</option>
                            <option value="shipped" ${o.status === 'shipped' ? 'selected' : ''}>Shipped</option>
                            <option value="delivered" ${o.status === 'delivered' ? 'selected' : ''}>Delivered</option>
                        </select>
                    </td>
                    <td>${new Date(o.created_at).toLocaleString()}</td>
                </tr>
            `).join('');
        }

        async function loadPayments() {
            const res = await fetch('/api/payments');
            const data = await res.json();
            const tbody = document.getElementById('paymentTableBody');
            tbody.innerHTML = data.map(p => `
                <tr>
                    <td>${p.id}</td>
                    <td>#${p.order_id}</td>
                    <td>${p.phone}</td>
                    <td>$${p.amount.toFixed(2)}</td>
                    <td>${p.status}</td>
                    <td>${p.transaction_id || 'N/A'}</td>
                    <td>${new Date(p.created_at).toLocaleString()}</td>
                </tr>
            `).join('');
        }

        // ----- Auto-refresh every 30 seconds -----
        setInterval(() => {
            loadStats();
            loadOrders();
            loadPayments();
        }, 30000);
    }
});