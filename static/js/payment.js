/**
 * 支付页面 JavaScript
 */

const COUNTRY_CURRENCY_MAP = {
    SG: 'SGD', US: 'USD', TR: 'TRY', JP: 'JPY',
    HK: 'HKD', GB: 'GBP', EU: 'EUR', AU: 'AUD',
    CA: 'CAD', IN: 'INR', BR: 'BRL', MX: 'MXN',
};

let selectedPlan = 'plus';
let generatedLink = '';

function showPaymentFeedback(message, level = 'info') {
    const statusEl = document.getElementById('open-status');
    if (statusEl) {
        statusEl.textContent = String(message || '');
    }

    if (typeof toast?.[level] === 'function') {
        toast[level](message);
        return;
    }
    if (typeof ui?.showToast === 'function') {
        ui.showToast(message, level);
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadAccounts();
});

// 加载账号列表
async function loadAccounts() {
    try {
        const resp = await fetch('/api/accounts?page=1&page_size=100&status=active');
        const data = await resp.json();
        const sel = document.getElementById('account-select');
        sel.innerHTML = '<option value="">-- 请选择账号 --</option>';
        (data.accounts || []).forEach(acc => {
            const opt = document.createElement('option');
            opt.value = acc.id;
            opt.textContent = acc.email;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error('加载账号失败:', e);
    }
}

// 国家切换
function onCountryChange() {
    const country = document.getElementById('country-select').value;
    const currency = COUNTRY_CURRENCY_MAP[country] || 'USD';
    document.getElementById('currency-display').value = currency;
}

// 选择套餐
function selectPlan(plan) {
    selectedPlan = plan;
    document.getElementById('plan-plus').classList.toggle('selected', plan === 'plus');
    document.getElementById('plan-team').classList.toggle('selected', plan === 'team');
    document.getElementById('team-options').classList.toggle('show', plan === 'team');
    // 隐藏已生成的链接
    document.getElementById('link-box').classList.remove('show');
    generatedLink = '';
}

// 生成支付链接
async function generateLink() {
    const accountId = document.getElementById('account-select').value;
    if (!accountId) {
        showPaymentFeedback('请先选择账号', 'warning');
        return;
    }

    const country = document.getElementById('country-select').value || 'SG';

    const body = {
        account_id: parseInt(accountId),
        plan_type: selectedPlan,
        country: country,
    };

    if (selectedPlan === 'team') {
        body.workspace_name = document.getElementById('workspace-name').value || 'MyTeam';
        body.seat_quantity = parseInt(document.getElementById('seat-quantity').value) || 5;
        body.price_interval = document.getElementById('price-interval').value;
    }

    const btn = document.querySelector('.form-actions .btn-primary');
    if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

    try {
        const resp = await fetch('/api/payment/generate-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (data.success && data.link) {
            generatedLink = data.link;
            document.getElementById('link-text').value = data.link;
            document.getElementById('link-box').classList.add('show');
            showPaymentFeedback('支付链接生成成功', 'success');
        } else {
            showPaymentFeedback(data.detail || '生成链接失败', 'error');
        }
    } catch (e) {
        showPaymentFeedback('请求失败: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '生成支付链接'; }
    }
}

// 复制链接
function copyLink() {
    if (!generatedLink) return;
    navigator.clipboard.writeText(generatedLink).then(() => {
        showPaymentFeedback('已复制到剪贴板', 'success');
    }).catch(() => {
        const ta = document.getElementById('link-text');
        ta.select();
        document.execCommand('copy');
        showPaymentFeedback('已复制到剪贴板', 'success');
    });
}

// 无痕打开浏览器（携带账号 cookie）
async function openIncognito() {
    if (!generatedLink) {
        showPaymentFeedback('请先生成链接', 'warning');
        return;
    }
    const accountId = document.getElementById('account-select').value;
    showPaymentFeedback('正在打开...', 'info');
    try {
        const body = { url: generatedLink };
        if (accountId) body.account_id = parseInt(accountId);

        const resp = await fetch('/api/payment/open-incognito', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (data.success) {
            showPaymentFeedback('已在无痕模式打开浏览器', 'success');
        } else {
            showPaymentFeedback(data.message || '未找到可用浏览器，请手动复制链接', 'warning');
        }
    } catch (e) {
        showPaymentFeedback('请求失败: ' + e.message, 'error');
    }
}
