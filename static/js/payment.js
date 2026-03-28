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

const paymentElements = {
    planPlus: document.getElementById('plan-plus'),
    planTeam: document.getElementById('plan-team'),
    accountSelect: document.getElementById('account-select'),
    countrySelect: document.getElementById('country-select'),
    currencyDisplay: document.getElementById('currency-display'),
    workspaceName: document.getElementById('workspace-name'),
    seatQuantity: document.getElementById('seat-quantity'),
    priceInterval: document.getElementById('price-interval'),
    teamOptions: document.getElementById('team-options'),
    linkBox: document.getElementById('link-box'),
    linkText: document.getElementById('link-text'),
    generateLinkBtn: document.getElementById('generate-link-btn'),
    copyLinkBtn: document.getElementById('copy-link-btn'),
    openIncognitoBtn: document.getElementById('open-incognito-btn'),
    openStatus: document.getElementById('open-status'),
};

function showPaymentFeedback(message, level = 'info') {
    if (paymentElements.openStatus) {
        paymentElements.openStatus.textContent = String(message || '');
    }

    if (typeof toast?.[level] === 'function') {
        toast[level](message);
        return;
    }
    if (typeof ui?.showToast === 'function') {
        ui.showToast(message, level);
    }
}

function renderPlanState() {
    paymentElements.planPlus?.classList.toggle('selected', selectedPlan === 'plus');
    paymentElements.planTeam?.classList.toggle('selected', selectedPlan === 'team');
    paymentElements.teamOptions?.classList.toggle('show', selectedPlan === 'team');
    paymentElements.linkBox?.classList.remove('show');
}

function setGenerateButtonBusy(isBusy) {
    if (!paymentElements.generateLinkBtn) return;
    paymentElements.generateLinkBtn.disabled = isBusy;
    paymentElements.generateLinkBtn.textContent = isBusy ? '生成中...' : '生成支付链接';
}

async function loadAccounts() {
    if (!paymentElements.accountSelect) return;

    try {
        const data = await api.get('/accounts?page=1&page_size=100&status=active');
        paymentElements.accountSelect.innerHTML = '<option value="">-- 请选择账号 --</option>';
        (data.accounts || []).forEach((acc) => {
            const opt = document.createElement('option');
            opt.value = acc.id;
            opt.textContent = acc.email;
            paymentElements.accountSelect.appendChild(opt);
        });
    } catch (error) {
        console.error('加载账号失败:', error);
    }
}

function onCountryChange() {
    const country = paymentElements.countrySelect?.value || 'US';
    const currency = COUNTRY_CURRENCY_MAP[country] || 'USD';
    if (paymentElements.currencyDisplay) {
        paymentElements.currencyDisplay.value = currency;
    }
}

function selectPlan(plan) {
    selectedPlan = plan;
    generatedLink = '';
    renderPlanState();
}

async function generateLink() {
    const accountId = paymentElements.accountSelect?.value || '';
    if (!accountId) {
        showPaymentFeedback('请先选择账号', 'warning');
        return;
    }

    const body = {
        account_id: parseInt(accountId, 10),
        plan_type: selectedPlan,
        country: paymentElements.countrySelect?.value || 'SG',
    };

    if (selectedPlan === 'team') {
        body.workspace_name = paymentElements.workspaceName?.value || 'MyTeam';
        body.seat_quantity = parseInt(paymentElements.seatQuantity?.value || '5', 10) || 5;
        body.price_interval = paymentElements.priceInterval?.value || 'month';
    }

    setGenerateButtonBusy(true);
    try {
        const data = await api.post('/payment/generate-link', body);
        if (data.success && data.link) {
            generatedLink = data.link;
            if (paymentElements.linkText) paymentElements.linkText.value = data.link;
            paymentElements.linkBox?.classList.add('show');
            showPaymentFeedback('支付链接生成成功', 'success');
            return;
        }
        showPaymentFeedback(data.detail || '生成链接失败', 'error');
    } catch (error) {
        showPaymentFeedback(`请求失败: ${error.message}`, 'error');
    } finally {
        setGenerateButtonBusy(false);
    }
}

function copyLink() {
    if (!generatedLink) return;
    navigator.clipboard.writeText(generatedLink).then(() => {
        showPaymentFeedback('已复制到剪贴板', 'success');
    }).catch(() => {
        const textarea = paymentElements.linkText;
        textarea?.select();
        document.execCommand('copy');
        showPaymentFeedback('已复制到剪贴板', 'success');
    });
}

async function openIncognito() {
    if (!generatedLink) {
        showPaymentFeedback('请先生成链接', 'warning');
        return;
    }

    showPaymentFeedback('正在打开...', 'info');
    try {
        const body = { url: generatedLink };
        const accountId = paymentElements.accountSelect?.value || '';
        if (accountId) {
            body.account_id = parseInt(accountId, 10);
        }
        const data = await api.post('/payment/open-incognito', body);
        if (data.success) {
            showPaymentFeedback('已在无痕模式打开浏览器', 'success');
            return;
        }
        showPaymentFeedback(data.message || '未找到可用浏览器，请手动复制链接', 'warning');
    } catch (error) {
        showPaymentFeedback(`请求失败: ${error.message}`, 'error');
    }
}

function bindPaymentPageEvents() {
    paymentElements.planPlus?.addEventListener('click', () => selectPlan('plus'));
    paymentElements.planTeam?.addEventListener('click', () => selectPlan('team'));
    paymentElements.countrySelect?.addEventListener('change', onCountryChange);
    paymentElements.generateLinkBtn?.addEventListener('click', () => {
        void generateLink();
    });
    paymentElements.copyLinkBtn?.addEventListener('click', copyLink);
    paymentElements.openIncognitoBtn?.addEventListener('click', () => {
        void openIncognito();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    bindPaymentPageEvents();
    renderPlanState();
    onCountryChange();
    void loadAccounts();
});
