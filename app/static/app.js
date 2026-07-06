// Глобальная защита: не даём <img> грузить src, который не является ссылкой
// (имена контрагентов/организаций иногда протекают в :src при рендере Alpine).
// Перехватываем setAttribute('src', ...) и пропускаем только валидные пути.
(function () {
  const looksLikeUrl = (v) => typeof v === 'string' &&
    (/^\//.test(v) || /^https?:/.test(v) || /^data:/.test(v) || /^blob:/.test(v));
  const origSetAttr = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (this.tagName === 'IMG' && name === 'src' && value && !looksLikeUrl(value)) {
      // мусорный src (имя вместо ссылки) — не ставим, прячем картинку
      this.removeAttribute('src');
      this.style.display = 'none';
      return;
    }
    return origSetAttr.call(this, name, value);
  };
  // На случай прямой установки через свойство .src
  const desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  if (desc && desc.set) {
    Object.defineProperty(HTMLImageElement.prototype, 'src', {
      configurable: true,
      enumerable: desc.enumerable,
      get: desc.get,
      set(value) {
        if (value && !looksLikeUrl(value)) { this.style.display = 'none'; return; }
        desc.set.call(this, value);
      },
    });
  }
})();

function app() {
  return {
    currentUser: null,
    tab: 'dashboard',
    mobileMenuOpen: false,
    navMenu: '',
    openTip: '',
    tipX: 0,
    tipY: 0,
    tipTexts: {
      type: 'Выберите, как оплачивается сервис:<br><br><b>Подписка</b> — платите фиксированную сумму каждый период (например, 500 ₽ в месяц за онлайн-сервис).<br><br><b>Баланс (Периодическое списание)</b> — держите деньги на счёте, раз в период списывается вся сумма сразу.<br><br><b>Баланс (Ежедневное списание)</b> — деньги на счёте тратятся понемногу каждый день (например, хостинг). Стоимость указываете за месяц.<br><br><b>Разовый платёж</b> — оплата один раз (лицензия, разовая услуга).',
      bday: 'Число месяца, когда со счёта списывается сумма. Например, «5» — деньги спишутся 5-го числа каждого месяца.<br><br>Если оставить пустым, программа не будет сама вычитать деньги — вы ведёте баланс вручную.',
      minbal: 'Когда денег на счёте останется меньше этой суммы, программа пришлёт предупреждение — пора пополнить.<br><br>Например, поставьте «1000»: как только баланс опустится до 1000 ₽, придёт уведомление. Оставьте 0, если не нужно.',
      daysleft: 'Программа сама посчитает, на сколько дней хватит денег (делит баланс на дневной расход), и предупредит заранее.<br><br>Например, «10» — придёт уведомление, когда денег останется примерно на 10 дней. Работает, если указана стоимость за месяц.',
      renew: 'Включите, если оплата списывается сама (например, привязана карта).<br><br>Тогда программа просто напомнит о платеже заранее, но не будет требовать отмечать оплату вручную. Если выключено — после оплаты нажимаете «Отметить оплату», чтобы платёж ушёл из списка предстоящих.',
    },
    appReady: false,
    dashMode: 'year',
    dashPeriod: '',
    dashYear: '',
    calRef: new Date(),
    toasts: [],
    theme: 'dark',
    accent: 'amber',
    accentColors: [
      { id: 'amber',     name: 'Янтарь',    light: '#D97706', dark: '#E8951F' },
      { id: 'terracotta',name: 'Терракота', light: '#C2612F', dark: '#DB8155' },
      { id: 'emerald',   name: 'Изумруд',   light: '#0F766E', dark: '#2DD4BF' },
      { id: 'indigo',    name: 'Индиго',    light: '#4F46E5', dark: '#818CF8' },
      { id: 'rose',      name: 'Роза',      light: '#BE185D', dark: '#F472B6' },
      { id: 'slate',     name: 'Графит',    light: '#475569', dark: '#94A3B8' },
      { id: 'ocean',     name: 'Океан',     light: '#0369A1', dark: '#38BDF8' },
      { id: 'olive',     name: 'Олива',     light: '#4D7C0F', dark: '#A3E635' },
    ],

    // Смена своего пароля (для требования сменить admin/admin)
    pwForm: null,

    stats: {},
    subscriptions: [],
    organizations: [],
    contractors: [],
    employees: [],
    categories: [],
    paymentMethods: [],
    users: [],
    webhooks: [],

    subSearch: '',
    filterOrg: '',
    filterType: '',
    filterMenuOpen: false,
    subView: (() => { const v = localStorage.getItem('oops-sub-view'); return (v === 'large' || v === 'list') ? v : 'large'; })(),
    expandedSub: null,
    notifLogs: [],
    notifLogsOpen: false,
    showAdvanced: false,

    // Встроенные SVG-иконки (категории / способы оплаты / каналы)
    builtinCatIcons: [
      '/static/icons/builtin/cat-internet.svg',
      '/static/icons/builtin/cat-hosting.svg',
      '/static/icons/builtin/cat-cloud.svg',
      '/static/icons/builtin/cat-software.svg',
      '/static/icons/builtin/cat-phone.svg',
      '/static/icons/builtin/cat-sms.svg',
      '/static/icons/builtin/cat-vpn.svg',
      '/static/icons/builtin/cat-security.svg',
      '/static/icons/builtin/cat-video.svg',
      '/static/icons/builtin/cat-music.svg',
      '/static/icons/builtin/cat-ads.svg',
      '/static/icons/builtin/cat-design.svg',
      '/static/icons/builtin/cat-analytics.svg',
      '/static/icons/builtin/cat-domain.svg',
      '/static/icons/builtin/cat-email.svg',
      '/static/icons/builtin/cat-ai.svg',
      '/static/icons/builtin/cat-office.svg',
      '/static/icons/builtin/cat-other.svg',
    ],
    builtinPayIcons: [
      '/static/icons/builtin/visa.svg',
      '/static/icons/builtin/mastercard.svg',
      '/static/icons/builtin/mir.svg',
      '/static/icons/builtin/sbp.svg',
      '/static/icons/builtin/card.svg',
      '/static/icons/builtin/bank-transfer.svg',
      '/static/icons/builtin/invoice.svg',
      '/static/icons/builtin/cash.svg',
      '/static/icons/builtin/google-pay.svg',
      '/static/icons/builtin/apple-pay.svg',
      '/static/icons/builtin/google-play.svg',
      '/static/icons/builtin/app-store.svg',
      '/static/icons/builtin/bitcoin.svg',
    ],

    // Типы каналов уведомлений (с иконками)
    channelKinds: [
      { id: 'webhook',  label: 'Webhook',   icon: '/static/icons/builtin/webhook.svg' },
      { id: 'email',    label: 'E-mail',    icon: '/static/icons/builtin/email.svg' },
      { id: 'telegram', label: 'Telegram',  icon: '/static/icons/builtin/telegram.svg' },
      { id: 'bitrix24', label: 'Bitrix24',  icon: '/static/icons/builtin/bitrix24.svg' },
    ],

    // Список вариантов «N дней до события» (0–31)
    notifyDayOptions: [0, 1, 2, 3, 5, 7, 10, 14, 30],

    subForm: null,
    subDetails: null,
    simpleForm: { open: false, data: {}, fields: [], title: '' },

    // Кастомный dropdown с иконками (категория/способ оплаты в форме подписки)
    iconDropdown: '', // '' | 'category' | 'payment'

    // Поиск контрагента в форме подписки
    contractorSearchOpen: false,
    contractorSearch: '',

    updateDragging: false,
    updateLog: '',
    importLog: '',
    backups: [],
    backupsExpanded: false,
    appVersion: '',
    updateChecking: false,
    updateInfo: null,
    backdropDown: false,

    get tabs() {
      // Полный плоский список (для мобильного меню и поиска подписи)
      const base = [
        { id: 'dashboard', label: 'Сводка' },
        { id: 'subscriptions', label: 'Подписки' },
        { id: 'calendar', label: 'Календарь' },
        { id: 'organizations', label: 'Организации' },
        { id: 'contractors', label: 'Контрагенты' },
        { id: 'employees', label: 'Сотрудники' },
        { id: 'categories', label: 'Справочники' },
      ];
      if (this.currentUser?.role === 'admin') {
        base.push({ id: 'webhooks', label: 'Уведомления' });
        base.push({ id: 'users', label: 'Доступы' });
        base.push({ id: 'system', label: 'Система' });
      }
      return base;
    },

    // Основные вкладки — всегда на виду
    get mainTabs() {
      return [
        { id: 'dashboard', label: 'Сводка' },
        { id: 'subscriptions', label: 'Подписки' },
        { id: 'calendar', label: 'Календарь' },
      ];
    },

    // Группа «Справочники» (выпадающее меню)
    get refTabs() {
      return [
        { id: 'organizations', label: 'Организации' },
        { id: 'contractors', label: 'Контрагенты' },
        { id: 'employees', label: 'Сотрудники' },
        { id: 'categories', label: 'Категории и оплата' },
      ];
    },

    // Группа «Администрирование» (только admin)
    get adminTabs() {
      if (this.currentUser?.role !== 'admin') return [];
      return [
        { id: 'webhooks', label: 'Уведомления' },
        { id: 'users', label: 'Доступы' },
        { id: 'system', label: 'Система' },
      ];
    },

    // Активна ли вкладка из группы (для подсветки кнопки группы)
    isRefActive() { return this.refTabs.some(t => t.id === this.tab); },
    isAdminActive() { return this.adminTabs.some(t => t.id === this.tab); },

    get currentTabLabel() {
      const t = this.tabs.find(x => x.id === this.tab);
      return t ? t.label : '';
    },

    get filteredSubs() {
      let r = this.subscriptions;
      if (this.subSearch) {
        const q = this.subSearch.toLowerCase();
        r = r.filter(s => (s.name || '').toLowerCase().includes(q)
          || (s.notes || '').toLowerCase().includes(q)
          || (s.organization?.name || '').toLowerCase().includes(q));
      }
      if (this.filterOrg) r = r.filter(s => s.organization_id == this.filterOrg);
      if (this.filterType) r = r.filter(s => s.sub_type === this.filterType);
      return r;
    },

    // Оценка «хватит до» для балансовых счетов: баланс ÷ стоимость за период.
    // Возвращает {months, date} или null, если посчитать нельзя.
    // Доли по организациям (для кольца на дашборде)
    get orgShares() {
      const list = this.stats.by_organization || [];
      const total = list.reduce((s, o) => s + (o.monthly || 0), 0);
      if (total <= 0) return [];
      return list.map(o => ({
        name: o.name,
        monthly: o.monthly,
        pct: Math.round((o.monthly / total) * 100),
      }));
    },

    donutColor(i) {
      const palette = ['var(--accent)', '#0EA5E9', '#10B981', '#94A3B8', '#A855F7', '#F43F5E', '#F59E0B', '#14B8A6'];
      return palette[i % palette.length];
    },

    get donutSegments() {
      const shares = this.orgShares;
      const total = shares.reduce((s, o) => s + o.monthly, 0);
      if (total <= 0) return [];
      const C = 2 * Math.PI * 70;
      let offset = 0;
      return shares.map((sh, i) => {
        const frac = sh.monthly / total;
        const len = frac * C;
        const seg = { color: this.donutColor(i), dash: `${len} ${C - len}`, offset: -offset };
        offset += len;
        return seg;
      });
    },

    // Готовая SVG-разметка кольца (x-for внутри SVG в Alpine глючит — генерируем строкой)
    get donutSvg() {
      let s = '<circle cx="90" cy="90" r="70" fill="none" stroke="var(--line2)" stroke-width="18"/>';
      for (const seg of this.donutSegments) {
        s += `<circle cx="90" cy="90" r="70" fill="none" stroke="${seg.color}" stroke-width="18" stroke-dasharray="${seg.dash}" stroke-dashoffset="${seg.offset}" transform="rotate(-90 90 90)"/>`;
      }
      const n = this.orgShares.length;
      s += `<text x="90" y="84" text-anchor="middle" font-size="30" font-weight="600" fill="var(--ink)" style="font-family:var(--mono)">${n}</text>`;
      s += `<text x="90" y="104" text-anchor="middle" font-size="12" fill="var(--faint)">${this.orgWord(n)}</text>`;
      return s;
    },

    // Готовая SVG-разметка графика динамики
    get trendSvg() {
      const pts = this.historyPoints;
      if (pts.length < 2) return '';
      const line = pts.map(p => `${p.x},${p.y}`).join(' ');
      const last = pts[pts.length - 1];
      const area = `${pts[0].x},${this.trendH} ` + line + ` ${last.x},${this.trendH}`;
      let s = `<polyline points="${area}" fill="var(--accent-dim)" stroke="none"/>`;
      s += `<polyline points="${line}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
      for (const p of pts) {
        s += `<circle cx="${p.x}" cy="${p.y}" r="3" fill="var(--accent)"/>`;
      }
      return s;
    },

    orgWord(n) {
      const m10 = n % 10, m100 = n % 100;
      if (m10 === 1 && m100 !== 11) return 'организация';
      if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'организации';
      return 'организаций';
    },

    toggleTip(id, ev) {
      if (this.openTip === id) { this.openTip = ''; return; }
      this.openTip = id;
      const btn = ev.currentTarget;
      const r = btn.getBoundingClientRect();
      // позиционируем поповер под кнопкой, по центру
      this.tipX = r.left + r.width / 2;
      this.tipY = r.bottom + 8;
    },

    monthWord(n) {
      const m10 = n % 10, m100 = n % 100;
      if (m10 === 1 && m100 !== 11) return 'месяц';
      if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'месяца';
      return 'месяцев';
    },

    paymentWord(n) {
      const m10 = n % 10, m100 = n % 100;
      if (m10 === 1 && m100 !== 11) return 'платёж';
      if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'платежа';
      return 'платежей';
    },

    trendW: 600,
    trendH: 180,

    // История снимков (все периоды)
    get dashHistory() {
      return this.stats.history || [];
    },
    // Список годов из истории
    get dashYears() {
      const ys = new Set();
      for (const h of this.dashHistory) ys.add((h.period || '').split('-')[0]);
      return [...ys].filter(Boolean).sort();
    },
    periodLabel(period) {
      const [y, m] = (period || '').split('-');
      const mo = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
      return (mo[parseInt(m, 10) - 1] || '') + ' ' + y;
    },
    // Значение «Ежемесячно» под выбранный фильтр — строго по факту из снимков
    get dashMonthly() {
      if (this.dashMode === 'month') {
        const snap = this.dashHistory.find(h => h.period === this.dashPeriod);
        return snap ? snap.total : null;   // null = нет данных за этот месяц
      }
      // режим «Год»: средний фактический расход по месяцам, где есть снимки
      const inYear = this.dashHistory.filter(h => (h.period || '').startsWith(this.dashYear + '-'));
      if (!inYear.length) return null;
      return inYear.reduce((s, h) => s + h.total, 0) / inYear.length;
    },
    // Значение «В год» под фильтр — сумма фактических снимков за год
    get dashYearly() {
      const inYear = this.dashHistory.filter(h => (h.period || '').startsWith(this.dashYear + '-'));
      if (!inYear.length) return null;
      return inYear.reduce((s, h) => s + h.total, 0);
    },
    // Сколько реальных месяцев учтено в текущем году (для подписи)
    get dashYearMonths() {
      return this.dashHistory.filter(h => (h.period || '').startsWith(this.dashYear + '-')).length;
    },

    // Инициал и цвет аватара по имени
    initial(name) {
      return (name || '?').trim().charAt(0).toUpperCase();
    },
    _avatarIdx(name) {
      let h = 0;
      const s = name || '';
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
      return h % 8;
    },
    avatarBg(name) {
      const bg = ['#FBEAD0','#DCEBFB','#D8F0DF','#EFEAF7','#FCE4EC','#E0F2F1','#FFF3E0','#ECEFF1'];
      return bg[this._avatarIdx(name)];
    },
    avatarFg(name) {
      const fg = ['#B45309','#1D66B0','#177245','#7C3AED','#C2185B','#00796B','#E65100','#455A64'];
      return fg[this._avatarIdx(name)];
    },
    formatDayMonth(iso) {
      if (!iso) return '';
      const d = new Date(iso + (iso.length <= 10 ? 'T00:00:00' : ''));
      const mo = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
      return d.getDate() + ' ' + mo[d.getMonth()];
    },
    orgBarPct(v) {
      const list = this.stats.by_organization || [];
      const max = Math.max(...list.map(o => o.monthly || 0), 1);
      return Math.max(2, Math.round((v / max) * 100));
    },

    get historyPoints() {
      const hist = this.stats.history || [];
      if (hist.length < 2) return [];
      const vals = hist.map(h => h.total);
      const min = Math.min(...vals), max = Math.max(...vals);
      const range = (max - min) || 1;
      const W = this.trendW, H = this.trendH, padY = 24, padX = 10;
      const stepX = (W - padX * 2) / (hist.length - 1);
      const monthShort = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
      return hist.map((h, i) => {
        const x = padX + i * stepX;
        const y = H - padY - ((h.total - min) / range) * (H - padY * 2);
        const mo = parseInt((h.period || '').split('-')[1], 10) - 1;
        return { x: Math.round(x), y: Math.round(y), label: monthShort[mo] || '', total: h.total };
      });
    },

    get trendLine() {
      return this.historyPoints.map(p => `${p.x},${p.y}`).join(' ');
    },

    get trendArea() {
      const pts = this.historyPoints;
      if (pts.length < 2) return '';
      const last = pts[pts.length - 1];
      return `${pts[0].x},${this.trendH} ` + pts.map(p => `${p.x},${p.y}`).join(' ') + ` ${last.x},${this.trendH}`;
    },

    lastsEstimate(s) {
      const balance = Number(s.balance) || 0;
      const price = Number(s.price) || 0;
      if (balance <= 0 || price <= 0) return null;

      let totalDays;
      if (s.sub_type === 'balance_daily' || s.daily_charge) {
        // price — сумма за месяц, списывается посуточно
        const perDay = price / 30;
        totalDays = balance / perDay;
      } else {
        // обычный счёт: на сколько периодов хватит × длина периода
        const cycle = s.cycle || 'monthly';
        const freq = Number(s.frequency) || 1;
        const daysPer = { daily: 1, weekly: 7, monthly: 30, yearly: 365,
                          day: 1, week: 7, month: 30, year: 365 }[cycle] || 30;
        const periodDays = daysPer * freq;
        totalDays = (balance / price) * periodDays;
      }

      const months = totalDays / 30;
      const until = new Date();
      until.setDate(until.getDate() + Math.floor(totalDays));
      return { months, totalDays, date: until };
    },

    // Подпись текущего месяца («Июнь 2026»)
    get calLabel() {
      const m = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
      return m[this.calRef.getMonth()] + ' ' + this.calRef.getFullYear();
    },

    calPrev() { const d = new Date(this.calRef); d.setMonth(d.getMonth() - 1); this.calRef = d; },
    calNext() { const d = new Date(this.calRef); d.setMonth(d.getMonth() + 1); this.calRef = d; },
    calToday() { this.calRef = new Date(); },

    // Сетка календаря: массив недель, каждая — 7 ячеек {day, inMonth, isToday, events[]}
    get calendarGrid() {
      const year = this.calRef.getFullYear();
      const month = this.calRef.getMonth();
      const today = new Date(); today.setHours(0, 0, 0, 0);

      // все платежи этого месяца, разложенные по числу
      const byDay = {};
      const monthStart = new Date(year, month, 1);
      const monthEnd = new Date(year, month + 1, 0);
      for (const s of this.subscriptions) {
        if (!s.is_active) continue;
        const paidUntil = s.paid_until ? new Date(s.paid_until + 'T00:00:00') : null;
        for (const d of this.upcomingPaymentDates(s, monthStart, monthEnd)) {
          const k = d.getDate();
          // оплачено: покрыто отметкой оплаты, либо автосписание с прошедшей датой
          const paid = (paidUntil && paidUntil >= d) || (s.auto_renew && d < today);
          (byDay[k] = byDay[k] || []).push({
            id: s.id, name: s.name, amount: Number(s.price) || 0,
            currency: s.currency || 'RUB', logo_url: s.contractor?.logo_url || '',
            paid,
          });
        }
      }

      // первый день сетки — понедельник недели, в которую попадает 1-е число
      const firstDow = (monthStart.getDay() + 6) % 7; // 0=Пн
      const gridStart = new Date(year, month, 1 - firstDow);

      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const weeksNeeded = Math.ceil((firstDow + daysInMonth) / 7);

      // плоский массив ячеек — порядок гарантированно правильный (сверху вниз)
      const cells = [];
      let cur = new Date(gridStart);
      for (let i = 0; i < weeksNeeded * 7; i++) {
        const inMonth = cur.getMonth() === month;
        cells.push({
          key: cur.getFullYear() + '-' + cur.getMonth() + '-' + cur.getDate(),
          day: cur.getDate(),
          inMonth,
          isToday: cur.getTime() === today.getTime(),
          events: inMonth ? (byDay[cur.getDate()] || []) : [],
        });
        cur.setDate(cur.getDate() + 1);
      }
      return cells;
    },

    // Сумма платежей за отображаемый месяц
    get calMonthTotal() {
      let t = 0;
      for (const cell of this.calendarGrid)
        for (const e of cell.events) t += e.amount;
      return t;
    },

    // Список дат платежей подписки от from до to
    upcomingPaymentDates(s, from, to) {
      const out = [];
      if (s.sub_type === 'onetime') {
        if (s.next_payment) {
          const d = new Date(s.next_payment + 'T00:00:00');
          if (d >= from && d <= to) out.push(d);
        }
        return out;
      }
      const day = s.billing_day ? Math.min(s.billing_day, 28) : null;
      if (!day) return out;
      let cursor = new Date(from.getFullYear(), from.getMonth(), day);
      while (cursor < from) cursor.setMonth(cursor.getMonth() + 1);
      while (cursor <= to) {
        out.push(new Date(cursor));
        cursor.setMonth(cursor.getMonth() + 1);
      }
      return out;
    },

    get detailRows() {
      if (!this.subDetails) return [];
      const s = this.subDetails;
      const fmt = this.fmt.bind(this);
      const rows = [];
      if (s.sub_type === 'onetime') {
        rows.push({ key: 'Дата оплаты', value: s.next_payment ? this.formatDateLong(s.next_payment) : null, featured: true });
      } else if (s.sub_type === 'recurring') {
        rows.push({ key: 'День списания', value: s.billing_day ? s.billing_day + ' числа каждого месяца' : 'не указан', featured: true });
      }
      rows.push(
        { key: 'Стоимость', value: fmt(s.price) + ' ' + s.currency, featured: true },
        { key: 'Периодичность', value: this.cycleLabel(s.cycle, s.frequency, s.sub_type) },
        { key: 'Организация', value: s.organization?.name },
        { key: 'Контрагент', value: s.contractor?.name },
        { key: 'Ответственный', value: s.employee?.full_name },
        { key: 'Категория', value: s.category ? ((this.isIconUrl(s.category.icon) ? '' : (s.category.icon ? s.category.icon + ' ' : '')) + s.category.name) : 'Без категории' },
        { key: 'Способ оплаты', value: s.payment_method ? ((this.isIconUrl(s.payment_method.icon) ? '' : (s.payment_method.icon ? s.payment_method.icon + ' ' : '')) + s.payment_method.name) : null },
        { key: 'Используется с', value: s.start_date ? this.formatDateLong(s.start_date) : null },
        { key: 'Дата отмены', value: s.cancellation_date ? this.formatDateLong(s.cancellation_date) : null },
        { key: 'URL', value: s.url, html: s.url ? `<a href="${s.url}" target="_blank">${s.url}</a>` : null },
        { key: 'Примечания', value: s.notes },
      );
      if (s.sub_type === 'balance' || s.sub_type === 'balance_daily') {
        const balanceRows = [
          { key: 'Текущий баланс', value: fmt(s.balance) + ' ' + s.currency, featured: true },
        ];
        if (s.sub_type === 'balance_daily') {
          const perDay = (Number(s.price) || 0) / 30;
          balanceRows.push({ key: 'Списание', value: 'ежедневно' });
          if (perDay > 0) balanceRows.push({ key: 'Расход в день', value: '≈ ' + fmt(perDay) + ' ' + s.currency });
        } else if (s.billing_day) {
          balanceRows.push({ key: 'День списания', value: s.billing_day + ' числа' });
        } else {
          balanceRows.push({ key: 'Списание', value: 'вручную (без автосписания)' });
        }
        if (s.min_balance) {
          balanceRows.push({ key: 'Минимальный баланс', value: fmt(s.min_balance) + ' ' + s.currency });
        }
        const est = this.lastsEstimate(s);
        if (est) {
          const d = est.date;
          const dateStr = String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear();
          let human;
          if (est.totalDays < 14) human = '≈' + Math.round(est.totalDays) + ' дн.';
          else if (est.months < 1.5) human = '≈' + Math.round(est.totalDays / 7) + ' нед.';
          else human = '≈' + Math.round(est.months) + ' мес.';
          balanceRows.push({ key: 'Хватит до', value: `${human} (до ${dateStr})`, featured: true });
        }
        rows.splice(0, 0, ...balanceRows);
      }
      return rows;
    },

    async init() {
      try {
        const r = await fetch('/api/auth/me', { credentials: 'include' });
        if (!r.ok) { window.location.href = '/login'; return; }
        this.currentUser = await r.json();
        // Восстановить последнюю открытую вкладку
        const savedTab = localStorage.getItem('oops-tab');
        if (savedTab) {
          const adminTabs = ['users', 'system'];
          if (adminTabs.includes(savedTab) && this.currentUser?.role !== 'admin') {
            this.tab = 'dashboard';
          } else {
            this.tab = savedTab;
          }
        }
        // Сохранять вкладку при каждом переключении
        this.$watch('tab', (v) => {
          localStorage.setItem('oops-tab', v);
          if (v === 'system' && this.currentUser?.role === 'admin') this.loadBackups();
        });
        await this.loadTheme();
        await this.loadAll();
        // если стартовали сразу на вкладке «Система» — подгрузить бэкапы (watch не сработает)
        if (this.tab === 'system' && this.currentUser?.role === 'admin') this.loadBackups();
        this.appReady = true;
      } catch {
        window.location.href = '/login';
      }
    },

    async loadTheme() {
      try {
        const r = await this.api('/api/system/theme');
        this.theme = r?.theme || localStorage.getItem('oops-theme') || 'dark';
      } catch {
        this.theme = localStorage.getItem('oops-theme') || 'dark';
      }
      this.accent = localStorage.getItem('oops-accent') || 'amber';
      localStorage.setItem('oops-theme', this.theme);
      document.documentElement.setAttribute('data-theme', this.theme);
      this.applyAccent();
    },

    applyAccent() {
      const c = this.accentColors.find(a => a.id === this.accent) || this.accentColors[0];
      const hex = this.theme === 'dark' ? c.dark : c.light;
      const root = document.documentElement;
      root.style.setProperty('--accent', hex);
      root.style.setProperty('--accent-hover', this._shade(hex, this.theme === 'dark' ? 20 : -20));
      root.style.setProperty('--accent-dim', this._hexA(hex, this.theme === 'dark' ? 0.16 : 0.10));
      root.style.setProperty('--accent-soft', this._hexA(hex, this.theme === 'dark' ? 0.16 : 0.14));
      root.style.setProperty('--accent-ink', this.theme === 'dark' ? this._shade(hex, 15) : this._shade(hex, -15));

      // Лёгкая тонировка фона и поверхностей под акцент (как в макете)
      if (this.theme === 'dark') {
        const surf = this._mix(hex, '#211C17', 0.04);
        const surf2 = this._mix(hex, '#2A241D', 0.05);
        const line = this._mix(hex, '#332B23', 0.05);
        root.style.setProperty('--bg', this._mix(hex, '#161311', 0.06));
        root.style.setProperty('--surface', surf);
        root.style.setProperty('--bg-card', surf);
        root.style.setProperty('--surface2', surf2);
        root.style.setProperty('--bg-elev', surf2);
        root.style.setProperty('--line', line);
        root.style.setProperty('--border', line);
      } else {
        const surf2 = this._mix(hex, '#FBF8F2', 0.05);
        const line = this._mix(hex, '#E9E3D9', 0.06);
        root.style.setProperty('--bg', this._mix(hex, '#F4F0E9', 0.06));
        root.style.setProperty('--surface', '#FFFFFF');
        root.style.setProperty('--bg-card', '#FFFFFF');
        root.style.setProperty('--surface2', surf2);
        root.style.setProperty('--bg-elev', surf2);
        root.style.setProperty('--line', line);
        root.style.setProperty('--border', line);
      }
    },

    // Смешать hex-цвет с базовым в пропорции t (0..1 доля первого)
    _mix(hex, base, t) {
      const a = parseInt(hex.slice(1), 16), b = parseInt(base.slice(1), 16);
      const ar=(a>>16)&255, ag=(a>>8)&255, ab=a&255;
      const br=(b>>16)&255, bg=(b>>8)&255, bb=b&255;
      const r = Math.round(ar*t + br*(1-t));
      const g = Math.round(ag*t + bg*(1-t));
      const bl = Math.round(ab*t + bb*(1-t));
      return '#' + ((1<<24) + (r<<16) + (g<<8) + bl).toString(16).slice(1);
    },

    _hexA(hex, a) {
      const n = parseInt(hex.slice(1), 16);
      return `rgba(${(n>>16)&255}, ${(n>>8)&255}, ${n&255}, ${a})`;
    },
    _shade(hex, pct) {
      const n = parseInt(hex.slice(1), 16);
      let r = (n>>16)&255, g = (n>>8)&255, b = n&255;
      const t = pct < 0 ? 0 : 255, p = Math.abs(pct) / 100;
      r = Math.round((t - r) * p) + r;
      g = Math.round((t - g) * p) + g;
      b = Math.round((t - b) * p) + b;
      return '#' + ((1<<24) + (r<<16) + (g<<8) + b).toString(16).slice(1);
    },

    setAccent(id) {
      this.accent = id;
      localStorage.setItem('oops-accent', id);
      this.applyAccent();
    },

    setSubView(v) {
      this.subView = v;
      this.expandedSub = null;
      localStorage.setItem('oops-sub-view', v);
    },

    toggleExpand(id) {
      this.expandedSub = this.expandedSub === id ? null : id;
    },

    async toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('oops-theme', this.theme);
      document.documentElement.setAttribute('data-theme', this.theme);
      this.applyAccent();
      try {
        await this.api('/api/system/theme', { method: 'POST', body: JSON.stringify({ theme: this.theme }) });
      } catch {}
    },

    async handleUploadFile(file) {
      if (!file) return;
      this.updateLog = 'Загрузка архива...';
      const formData = new FormData();
      formData.append('file', file);
      try {
        const r = await fetch('/api/system/upload-update', {
          method: 'POST',
          credentials: 'include',
          body: formData
        });
        const data = await r.json();
        if (r.ok && data.success) {
          this.updateLog = data.log + '\n\n⏳ Перезапуск... Подождите 10 секунд и обновите страницу.';
          this.toast('Обновление применено!', 'success');
          // Через 12 сек попробуем переподключиться
          setTimeout(() => window.location.reload(), 12000);
        } else {
          this.updateLog = data.detail || 'Ошибка обновления';
          this.toast('Ошибка обновления', 'error');
        }
      } catch (e) {
        this.updateLog = 'Ошибка: ' + e.message;
        this.toast('Ошибка загрузки', 'error');
      }
    },

    async checkUpdate() {
      this.updateChecking = true;
      this.updateInfo = null;
      try {
        this.updateInfo = await this.api('/api/system/check-update');
      } catch (e) {
        this.updateInfo = { error: 'Не удалось проверить обновления' };
      } finally {
        this.updateChecking = false;
      }
    },

    async loadBackups() {
      try {
        const r = await this.api('/api/system/backups');
        this.backups = r?.backups || [];
      } catch { this.backups = []; }
      // заодно версия
      try {
        const info = await this.api('/api/system/info');
        if (info?.app_version) this.appVersion = info.app_version;
      } catch {}
    },

    async restoreBackup(name) {
      if (!confirm(`Восстановить базу из «${name}»?\n\nТекущие данные будут заменены. Перед заменой автоматически создастся резервная копия текущей базы. После восстановления приложение перезапустится.`)) return;
      try {
        const r = await this.api('/api/system/backups/restore', {
          method: 'POST',
          body: JSON.stringify({ name })
        });
        if (r?.success) {
          this.importLog = (r.log || 'Восстановлено') + '\n\nПодождите ~5 секунд и обновите страницу (Ctrl+F5).';
          this.toast('База восстановлена, перезапуск...');
        }
      } catch {}
    },

    fmtBytes(n) {
      if (!n) return '0 Б';
      const u = ['Б', 'КБ', 'МБ', 'ГБ'];
      let i = 0; let v = n;
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
      return v.toFixed(i ? 1 : 0) + ' ' + u[i];
    },

    async exportData() {
      try {
        const r = await fetch('/api/system/export-data', { credentials: 'include' });
        if (!r.ok) {
          const d = await r.json();
          throw new Error(d.detail || 'Ошибка экспорта');
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        a.href = url;
        a.download = `Oops-Backup-${stamp}.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        this.toast('Экспорт сохранён');
      } catch (e) {
        this.toast(e.message || 'Ошибка экспорта', 'error');
      }
    },

    async importData(file) {
      if (!file) return;
      if (!confirm('Импорт заменит текущие подписки, справочники, webhooks и настройки. Можно загрузить ZIP-бэкап Oops или Wallos. Продолжить?')) return;
      this.importLog = 'Импорт данных...';
      const formData = new FormData();
      formData.append('file', file);
      try {
        const r = await fetch('/api/system/import-data', {
          method: 'POST',
          credentials: 'include',
          body: formData
        });
        const data = await r.json();
        if (!r.ok || !data.success) {
          throw new Error(data.detail || 'Ошибка импорта');
        }
        const parts = Object.entries(data.summary || {}).map(([k, v]) => `${k}: ${v}`);
        this.importLog = 'Импорт завершён\n' + parts.join('\n');
        await this.loadAll();
        await this.loadTheme();
        this.toast('Импорт завершён');
      } catch (e) {
        this.importLog = 'Ошибка: ' + (e.message || e);
        this.toast('Ошибка импорта', 'error');
      }
    },

    canEdit() {
      return this.currentUser?.role === 'admin' || this.currentUser?.role === 'manager';
    },

    async loadAll() {
      await Promise.all([
        this.loadSubscriptions(),
        this.loadOrganizations(),
        this.loadContractors(),
        this.loadEmployees(),
        this.loadCategories(),
        this.loadPaymentMethods(),
        this.loadStats(),
      ]);
      if (this.currentUser?.role === 'admin') {
        await Promise.all([this.loadUsers(), this.loadWebhooks()]);
      }
    },

    // Возвращает logo только если это валидный URL (а не мусорное имя из legacy-поля)
    logoSrc(v) {
      if (typeof v !== 'string') return '';
      const t = v.trim();
      if (t.startsWith('/') || t.startsWith('http://') || t.startsWith('https://') || t.startsWith('data:')) return t;
      return '';
    },

    // Хелпер: иконка может быть эмодзи или URL (/static/icons/...)
    isIconUrl(v) {
      return typeof v === 'string' && v.startsWith('/');
    },

    selectedCategory() {
      const id = this.subForm?.category_id;
      if (!id) return {};
      return this.categories.find(c => String(c.id) === String(id)) || {};
    },
    selectedPayment() {
      const id = this.subForm?.payment_method_id;
      if (!id) return {};
      return this.paymentMethods.find(p => String(p.id) === String(id)) || {};
    },
    pickCategory(id) {
      if (!this.subForm) return;
      this.subForm.category_id = id ? String(id) : '';
      this.iconDropdown = '';
    },
    pickPayment(id) {
      if (!this.subForm) return;
      this.subForm.payment_method_id = id ? String(id) : '';
      this.iconDropdown = '';
    },

    selectedContractor() {
      const id = this.subForm?.contractor_id;
      if (!id) return {};
      return this.contractors.find(c => String(c.id) === String(id)) || {};
    },
    filteredContractors() {
      const q = (this.contractorSearch || '').trim().toLowerCase();
      if (!q) return this.contractors;
      return this.contractors.filter(c => (c.name || '').toLowerCase().includes(q));
    },
    pickContractor(id) {
      this.subForm.contractor_id = id ? String(id) : '';
      this.contractorSearchOpen = false;
      this.contractorSearch = '';
    },
    // true если введённого названия нет среди контрагентов (точного совпадения)
    canCreateContractor() {
      const q = (this.contractorSearch || '').trim();
      if (!q) return false;
      return !this.contractors.some(c => (c.name || '').toLowerCase() === q.toLowerCase());
    },
    async createContractorInline() {
      const name = (this.contractorSearch || '').trim();
      if (!name) return;
      try {
        const created = await this.api('/api/contractors/', {
          method: 'POST',
          body: JSON.stringify({ name, website: '', logo_url: '', notes: '' })
        });
        await this.loadContractors();
        if (created?.id) {
          this.subForm.contractor_id = String(created.id);
        }
        this.toast(`Контрагент «${name}» добавлен`);
        this.contractorSearchOpen = false;
        this.contractorSearch = '';
      } catch {}
    },

    async loadStats() {
      this.stats = await this.api('/api/subscriptions/stats/dashboard');
      // дефолты фильтра: последний доступный период/год
      const hist = this.stats.history || [];
      if (hist.length && !this.dashPeriod) this.dashPeriod = hist[hist.length - 1].period;
      const years = [...new Set(hist.map(h => (h.period || '').split('-')[0]))].filter(Boolean).sort();
      if (years.length && !this.dashYear) this.dashYear = years[years.length - 1];
    },
    async loadSubscriptions() { this.subscriptions = await this.api('/api/subscriptions/'); },
    async loadOrganizations() { this.organizations = await this.api('/api/organizations/'); },
    async loadContractors() { this.contractors = await this.api('/api/contractors/'); },
    async loadEmployees() { this.employees = await this.api('/api/employees/'); },
    async loadCategories() { this.categories = await this.api('/api/categories/'); },
    async loadPaymentMethods() { this.paymentMethods = await this.api('/api/payment-methods/'); },
    async loadUsers() { this.users = await this.api('/api/users/'); },
    async loadWebhooks() { this.webhooks = await this.api('/api/webhooks/'); },

    async api(url, opts = {}) {
      const r = await fetch(url, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...opts });
      if (r.status === 401) { window.location.href = '/login'; return null; }
      if (!r.ok) {
        let msg = `Ошибка ${r.status}`;
        try {
          const d = await r.json();
          if (typeof d.detail === 'string') {
            msg = d.detail;
          } else if (Array.isArray(d.detail)) {
            // Pydantic validation errors: [{loc, msg, type}, ...]
            msg = d.detail.map(e => (e.loc ? e.loc.join('.') + ': ' : '') + (e.msg || JSON.stringify(e))).join('; ');
          } else if (d.detail) {
            msg = JSON.stringify(d.detail);
          } else if (d.message) {
            msg = d.message;
          }
        } catch {
          try { msg = (await r.text()).slice(0, 300) || msg; } catch {}
        }
        this.toast(msg, 'error');
        throw new Error(msg);
      }
      return r.json();
    },

    toast(text, type = 'success') {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, text, type });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 3000);
    },

    async logout() {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
      window.location.href = '/login';
    },

    fmt(n) {
      if (n == null) return '0';
      return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
    },

    channelKindLabel(kind) {
      return ({ webhook: 'Webhook', email: 'E-mail', telegram: 'Telegram', bitrix24: 'Bitrix24' })[kind || 'webhook'] || kind;
    },
    channelKindIcon(kind) {
      const k = this.channelKinds.find(c => c.id === (kind || 'webhook'));
      return k ? k.icon : '/static/icons/builtin/webhook.svg';
    },
    channelSubtitle(w) {
      const k = w.kind || 'webhook';
      if (k === 'webhook' || k === 'bitrix24') return (w.method || 'POST') + ' ' + (w.url || '—');
      try {
        const c = JSON.parse(w.config || '{}');
        if (k === 'email') return 'SMTP: ' + (c.smtp_host || '—') + ' → ' + (c.to_addr || '—');
        if (k === 'telegram') return 'Chat: ' + (c.chat_id || '—');
      } catch {}
      return '—';
    },

    contractorLogo(c) {
      if (!c) return '';
      return c.logo_url || '';
    },

    contractorInitials(c) {
      if (!c || !c.name) return '?';
      return c.name.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();
    },

    formatDate(d) {
      if (!d) return '';
      try {
        const dt = new Date(d);
        return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short' }).format(dt);
      } catch { return d; }
    },

    formatDateLong(d) {
      if (!d) return '';
      try {
        const dt = new Date(d);
        return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(dt);
      } catch { return d; }
    },

    roleLabel(role) {
      return { admin: 'Админ', manager: 'Менеджер', viewer: 'Просмотр' }[role] || role;
    },

    typeLabel(t) {
      return {
        recurring: 'Подписка',
        balance: 'Баланс (Периодическое списание)',
        balance_daily: 'Баланс (Ежедневное списание)',
        onetime: 'Разовый платёж',
      }[t] || t;
    },

    // Короткая подпись для бейджа на карточке (чтобы влезала в плашку)
    typeBadge(t) {
      return {
        recurring: 'Подписка',
        balance: 'Баланс',
        balance_daily: 'Баланс/день',
        onetime: 'Разовый',
      }[t] || t;
    },

    cycleLabel(c, f, type) {
      if (type === 'onetime') return 'Разовая оплата';
      const map = { daily: 'дн.', weekly: 'нед.', monthly: 'мес.', yearly: 'г.' };
      return `Каждые ${f || 1} ${map[c] || c}`;
    },

    openSubForm(s) {
      if (s && s.id) {
        this.subForm = { ...s };
        // Значения для <select> должны быть строками (Alpine сравнивает option value как строки)
        this.subForm.organization_id = s.organization_id != null ? String(s.organization_id) : '';
        this.subForm.contractor_id = s.contractor_id != null ? String(s.contractor_id) : '';
        this.subForm.employee_id = s.employee_id != null ? String(s.employee_id) : '';
        this.subForm.category_id = s.category_id != null ? String(s.category_id) : '';
        this.subForm.payment_method_id = s.payment_method_id != null ? String(s.payment_method_id) : '';
        this.subForm.balance_api_enabled = !!s.balance_api_url;
        // Нормализация полей уведомлений
        if (this.subForm.notify_enabled == null) this.subForm.notify_enabled = true;
        // В БД может быть несколько через запятую — для select берём первое
        const raw = (this.subForm.notify_days_before == null) ? '3' : String(this.subForm.notify_days_before);
        const first = raw.split(',')[0].trim();
        this.subForm.notify_days_before = first === '' ? '3' : first;
        if (this.subForm.notify_duration == null) this.subForm.notify_duration = '1';
        else this.subForm.notify_duration = String(this.subForm.notify_duration);
        if (this.subForm.overdue_notify_after == null) this.subForm.overdue_notify_after = '0';
        else this.subForm.overdue_notify_after = String(this.subForm.overdue_notify_after);
        if (this.subForm.cancellation_date == null) this.subForm.cancellation_date = '';
      } else {
        this.subForm = {
          name: '', sub_type: 'recurring', price: 0, currency: 'RUB',
          cycle: 'monthly', frequency: 1,
          next_payment: new Date().toISOString().split('T')[0],
          start_date: new Date().toISOString().split('T')[0],
          auto_renew: true, balance: 0, billing_day: 1, min_balance: 0,
          daily_charge: false, notify_days_left: 10,
          balance_api_url: '', balance_api_path: 'balance',
          balance_api_enabled: false,
          url: '', notes: '', is_active: true,
          notify_enabled: true,
          notify_days_before: '3',
          notify_duration: '1',
          overdue_notify_after: '0',
          cancellation_date: null,
          organization_id: '', contractor_id: '', employee_id: '',
          category_id: '', payment_method_id: '',
        };
      }
      // Принудительно проставить значения нативным <select> после того,
      // как Alpine отрендерит опции из x-for (обходит баг с поздним рендером)
      this.$nextTick(() => {
        setTimeout(() => this.syncSubFormSelects(), 0);
      });
    },

    // Уведомления: вспомогательные методы
    dayWord(n) {
      const m10 = n % 10, m100 = n % 100;
      if (m100 >= 11 && m100 <= 14) return 'дней';
      if (m10 === 1) return 'день';
      if (m10 >= 2 && m10 <= 4) return 'дня';
      return 'дней';
    },
    parseNotifyDays() {
      const s = this.subForm?.notify_days_before || '';
      return new Set(s.split(',').map(x => parseInt(x.trim(), 10)).filter(n => !isNaN(n)));
    },
    isDaySelected(d) {
      return this.parseNotifyDays().has(d);
    },
    toggleNotifyDay(d) {
      const set = this.parseNotifyDays();
      if (set.has(d)) set.delete(d); else set.add(d);
      this.subForm.notify_days_before = Array.from(set).sort((a, b) => a - b).join(',');
    },

    syncSubFormSelects() {
      // Только нативные <select> — для категории и способа оплаты теперь icon-dropdown,
      // им синхронизация не нужна (значение биндится через subForm.* напрямую)
      const map = {
        'sel-organization': this.subForm?.organization_id,
        'sel-contractor': this.subForm?.contractor_id,
        'sel-employee': this.subForm?.employee_id,
        'sel-notify-days': this.subForm?.notify_days_before,
      };
      for (const [id, val] of Object.entries(map)) {
        const el = document.getElementById(id);
        if (el) el.value = val ?? '';
      }
    },

    async saveSub() {
      if (!this.subForm.name) { this.toast('Введите название', 'error'); return; }
      // Для «Подписка» (recurring) день списания обязателен.
      // Для «Счёт/Баланс» (balance) день списания опциональный — если пустой, нет автосписания.
      if (this.subForm.sub_type === 'recurring') {
        const d = parseInt(this.subForm.billing_day);
        if (!d || d < 1 || d > 28) {
          this.toast('Укажите день списания (1–28) для подписки', 'error');
          return;
        }
      }
      if (this.subForm.sub_type === 'balance' && this.subForm.billing_day) {
        const d = parseInt(this.subForm.billing_day);
        if (d < 1 || d > 28) {
          this.toast('День списания должен быть от 1 до 28', 'error');
          return;
        }
      }
      if (this.subForm.sub_type === 'onetime' && !this.subForm.next_payment) {
        this.toast('Укажите дату оплаты для разового платежа', 'error');
        return;
      }
      const data = this.normalizeSubPayload();

      try {
        if (this.subForm.id) {
          await this.api(`/api/subscriptions/${this.subForm.id}`, { method: 'PUT', body: JSON.stringify(data) });
          this.toast('Подписка обновлена');
        } else {
          await this.api('/api/subscriptions/', { method: 'POST', body: JSON.stringify(data) });
          this.toast('Подписка создана');
        }
        this.subForm = null;
        await this.loadSubscriptions();
        await this.loadStats();
      } catch {}
    },

    // Готовит subForm к отправке: FK → число/null, пустые даты → null
    normalizeSubPayload() {
      const data = { ...this.subForm };
      for (const k of ['organization_id', 'contractor_id', 'employee_id', 'category_id', 'payment_method_id']) {
        data[k] = data[k] === '' || data[k] == null ? null : Number(data[k]);
      }
      // Пустые даты → null (Pydantic не принимает "")
      for (const k of ['next_payment', 'cancellation_date', 'start_date']) {
        if (!data[k]) data[k] = null;
      }
      if (!data.balance_api_enabled) {
        data.balance_api_url = '';
      }
      delete data.balance_api_enabled;
      return data;
    },

    async fetchBalance() {
      if (!this.subForm?.id) { this.toast('Сначала сохраните', 'error'); return; }
      try {
        const payload = this.normalizeSubPayload();
        await this.api(`/api/subscriptions/${this.subForm.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload)
        });
        const r = await this.api(`/api/subscriptions/${this.subForm.id}/fetch-balance`, { method: 'POST' });
        if (r?.success) {
          this.subForm.balance = r.balance;
          this.toast('Баланс обновлён: ' + r.balance);
        }
      } catch {}
    },

    async openSubDetails(id) {
      try { this.subDetails = await this.api(`/api/subscriptions/${id}`); } catch {}
    },

    openOrgForm(o) {
      this.simpleForm = {
        open: true,
        title: o ? 'Изменить организацию' : 'Новая организация',
        endpoint: '/api/organizations/',
        data: o ? { ...o } : { name: '', inn: '', notes: '' },
        fields: [
          { key: 'name', label: 'Название *' },
          { key: 'inn', label: 'ИНН' },
          { key: 'notes', label: 'Примечания', type: 'textarea' },
        ],
        reload: () => this.loadOrganizations(),
      };
    },

    openContractorForm(c) {
      this.simpleForm = {
        open: true,
        title: c ? 'Изменить контрагента' : 'Новый контрагент',
        endpoint: '/api/contractors/',
        data: c ? { ...c } : { name: '', inn: '', website: '', contact_info: '', logo_url: '', notes: '' },
        fields: [
          { key: 'name', label: 'Название *' },
          { key: 'inn', label: 'ИНН' },
          { key: 'website', label: 'Сайт' },
          { key: 'contact_info', label: 'Контакты', type: 'textarea' },
          { key: 'notes', label: 'Примечания', type: 'textarea' },
        ],
        reload: () => this.loadContractors(),
        // Спец-фичи для контрагента
        showLogoControls: true,
      };
    },

    // Создаёт контрагента «на лету», если он ещё не сохранён (нужно для загрузки лого).
    // Возвращает true если контрагент существует/создан, false если нельзя.
    async ensureContractorSaved() {
      if (this.simpleForm?.data?.id) return true;
      const name = (this.simpleForm?.data?.name || '').trim();
      if (!name) {
        this.toast('Сначала введите название контрагента', 'error');
        return false;
      }
      try {
        const body = {
          name,
          inn: this.simpleForm.data.inn || '',
          website: this.simpleForm.data.website || '',
          contact_info: this.simpleForm.data.contact_info || '',
          logo_url: this.simpleForm.data.logo_url || '',
          notes: this.simpleForm.data.notes || '',
        };
        const created = await this.api('/api/contractors/', { method: 'POST', body: JSON.stringify(body) });
        if (created?.id) {
          this.simpleForm.data.id = created.id;
          await this.loadContractors();
          return true;
        }
      } catch {}
      return false;
    },

    async uploadContractorLogo(file) {
      if (!file) return;
      if (!await this.ensureContractorSaved()) return;
      const formData = new FormData();
      formData.append('file', file);
      try {
        const r = await fetch(`/api/contractors/${this.simpleForm.data.id}/upload-logo`, {
          method: 'POST',
          credentials: 'include',
          body: formData
        });
        if (!r.ok) {
          const d = await r.json();
          this.toast(d.detail || 'Ошибка загрузки', 'error');
          return;
        }
        const data = await r.json();
        this.simpleForm.data.logo_url = data.logo_url;
        await this.loadContractors();
        await this.loadSubscriptions();
        this.toast('Логотип загружен');
      } catch (e) {
        this.toast('Ошибка загрузки', 'error');
      }
    },

    async fetchContractorFavicon() {
      if (!this.simpleForm?.data?.website) {
        this.toast('Сначала укажите сайт', 'error');
        return;
      }
      if (!await this.ensureContractorSaved()) return;
      try {
        const r = await this.api(`/api/contractors/${this.simpleForm.data.id}/fetch-favicon`, { method: 'POST' });
        if (r?.logo_url) {
          this.simpleForm.data.logo_url = r.logo_url;
          await this.loadContractors();
          await this.loadSubscriptions();
          this.toast('Логотип подобран автоматически');
        }
      } catch {}
    },

    async deleteContractorLogo() {
      if (!this.simpleForm?.data?.id) {
        // Лого ещё не сохранён на сервере — просто очистим локально
        this.simpleForm.data.logo_url = '';
        return;
      }
      if (!confirm('Удалить логотип?')) return;
      try {
        await this.api(`/api/contractors/${this.simpleForm.data.id}/logo`, { method: 'DELETE' });
        this.simpleForm.data.logo_url = '';
        await this.loadContractors();
        await this.loadSubscriptions();
        this.toast('Логотип удалён');
      } catch {}
    },

    openEmployeeForm(e) {
      this.simpleForm = {
        open: true,
        title: e ? 'Изменить сотрудника' : 'Новый сотрудник',
        endpoint: '/api/employees/',
        data: e ? { ...e } : { full_name: '', position: '', email: '', phone: '' },
        fields: [
          { key: 'full_name', label: 'ФИО *' },
          { key: 'position', label: 'Должность' },
          { key: 'email', label: 'Email', type: 'email' },
          { key: 'phone', label: 'Телефон' },
        ],
        reload: () => this.loadEmployees(),
      };
    },

    openCategoryForm(c) {
      this.simpleForm = {
        open: true,
        title: c ? 'Изменить категорию' : 'Новая категория',
        endpoint: '/api/categories/',
        data: c ? { ...c } : { name: '', icon: '/static/icons/builtin/cat-other.svg' },
        fields: [
          { key: 'name', label: 'Название *' },
          { key: 'icon', label: 'Иконка', type: 'iconpicker', builtinIcons: this.builtinCatIcons },
        ],
        reload: () => this.loadCategories(),
      };
    },

    openPaymentMethodForm(p) {
      this.simpleForm = {
        open: true,
        title: p ? 'Изменить способ оплаты' : 'Новый способ оплаты',
        endpoint: '/api/payment-methods/',
        data: p ? { ...p } : { name: '', details: '', icon: '/static/icons/builtin/card.svg' },
        fields: [
          { key: 'name', label: 'Название *' },
          { key: 'icon', label: 'Иконка', type: 'iconpicker', builtinIcons: this.builtinPayIcons },
          { key: 'details', label: 'Детали (карта, счёт)', type: 'textarea' },
        ],
        reload: () => this.loadPaymentMethods(),
      };
    },

    openUserForm(u) {
      this.simpleForm = {
        open: true,
        title: u ? 'Изменить пользователя' : 'Новый пользователь',
        endpoint: '/api/users/',
        data: u ? { ...u, password: '' } : { username: '', password: '', full_name: '', role: 'viewer' },
        fields: [
          { key: 'username', label: 'Логин *', disabled: !!u },
          { key: 'password', label: u ? 'Новый пароль (пусто = не менять)' : 'Пароль *', type: 'password' },
          { key: 'full_name', label: 'ФИО' },
          { key: 'role', label: 'Роль', type: 'select', options: [
            { value: 'admin', label: 'Админ' },
            { value: 'manager', label: 'Менеджер' },
            { value: 'viewer', label: 'Просмотр' },
          ]},
        ],
        reload: () => this.loadUsers(),
        method: u ? 'PATCH' : 'POST',
        urlSuffix: u ? u.id : '',
      };
    },

    openWebhookForm(w) {
      // Парсим существующий config (если есть)
      let cfg = {};
      try { cfg = w?.config ? JSON.parse(w.config) : {}; } catch {}

      const data = w ? { ...w, ...{
        cfg_smtp_host: cfg.smtp_host || '',
        cfg_smtp_port: cfg.smtp_port || 587,
        cfg_smtp_user: cfg.smtp_user || '',
        cfg_smtp_password: cfg.smtp_password || '',
        cfg_from_addr: cfg.from_addr || '',
        cfg_to_addr: cfg.to_addr || '',
        cfg_use_tls: cfg.use_tls !== false,
        cfg_bot_token: cfg.bot_token || '',
        cfg_chat_id: cfg.chat_id || cfg.dialog_id || '',
        cfg_user_id: cfg.user_id || '',
        cfg_system_message: !!cfg.system_message,
      } } : {
        name: 'Новый канал',
        kind: 'webhook',
        url: '', method: 'POST',
        headers: '{"Content-Type": "application/json"}',
        payload_template: '{\n  "name": "{{subscription_name}}",\n  "price": "{{subscription_price}}",\n  "currency": "{{subscription_currency}}",\n  "date": "{{subscription_date}}",\n  "org": "{{subscription_organization}}",\n  "message": "{{message}}"\n}',
        enabled: true, ignore_ssl: false,
        config: '{}',
        cfg_smtp_host: '', cfg_smtp_port: 587, cfg_smtp_user: '', cfg_smtp_password: '',
        cfg_from_addr: '', cfg_to_addr: '', cfg_use_tls: true,
        cfg_bot_token: '', cfg_chat_id: '', cfg_user_id: '', cfg_system_message: false,
      };

      this.simpleForm = {
        open: true,
        title: w ? 'Изменить канал уведомлений' : 'Новый канал уведомлений',
        endpoint: '/api/webhooks/',
        data,
        kind: 'notification_channel',  // спец-флаг для рендера
        reload: () => this.loadWebhooks(),
        method: w ? 'PUT' : 'POST',
        urlSuffix: w ? w.id : '',
        // Перед сохранением соберём config из cfg_* полей
        beforeSave: (d) => {
          const config = {};
          if (d.kind === 'email') {
            Object.assign(config, {
              smtp_host: d.cfg_smtp_host, smtp_port: Number(d.cfg_smtp_port) || 587,
              smtp_user: d.cfg_smtp_user, smtp_password: d.cfg_smtp_password,
              from_addr: d.cfg_from_addr, to_addr: d.cfg_to_addr, use_tls: !!d.cfg_use_tls,
            });
          } else if (d.kind === 'telegram') {
            Object.assign(config, { bot_token: d.cfg_bot_token, chat_id: d.cfg_chat_id });
          } else if (d.kind === 'bitrix24') {
            Object.assign(config, {
              user_id: d.cfg_user_id,
              chat_id: d.cfg_chat_id,
              system_message: !!d.cfg_system_message,
            });
          }
          d.config = JSON.stringify(config);
          // Уберём cfg_* поля из payload
          Object.keys(d).filter(k => k.startsWith('cfg_')).forEach(k => delete d[k]);
        },
      };
    },

    closeSimpleForm() {
      // Просто скрываем форму. data/fields остаются объектами (не null),
      // поэтому x-model и x-for внутри никогда не упираются в null.
      this.simpleForm.open = false;
    },

    async saveSimple() {
      if (!this.simpleForm) return;
      const sf = this.simpleForm;
      const method = sf.method || (sf.data.id ? 'PATCH' : 'POST');
      const url = sf.endpoint + (sf.urlSuffix || sf.data.id || '');
      const body = { ...sf.data };
      if (sf.endpoint === '/api/users/' && sf.data.id && !body.password) delete body.password;
      if (typeof sf.beforeSave === 'function') sf.beforeSave(body);
      try {
        await this.api(url, { method, body: JSON.stringify(body) });
        this.toast('Сохранено');
        this.closeSimpleForm();
        if (sf.reload) await sf.reload();
        await this.loadStats();
      } catch {}
    },

    async deleteItem(endpoint, id) {
      if (!confirm('Удалить?')) return;
      try {
        await this.api(`/api/${endpoint}/${id}`, { method: 'DELETE' });
        this.toast('Удалено');
        await this.loadAll();
      } catch {}
    },

    openChangePassword() {
      this.pwForm = { old_password: '', new_password: '', confirm: '' };
    },
    async saveChangePassword() {
      const f = this.pwForm;
      if (!f) return;
      if (!f.new_password || f.new_password.length < 4) { this.toast('Новый пароль минимум 4 символа', 'error'); return; }
      if (f.new_password !== f.confirm) { this.toast('Пароли не совпадают', 'error'); return; }
      try {
        await this.api('/api/auth/change-password', {
          method: 'POST',
          body: JSON.stringify({ old_password: f.old_password, new_password: f.new_password })
        });
        this.toast('Пароль изменён');
        this.pwForm = null;
        if (this.currentUser) this.currentUser.must_change_password = false;
      } catch {}
    },

    async markPaid(s) {
      if (!confirm(`Отметить оплату по «${s.name}»? Напоминания об этом платеже прекратятся до следующего периода.`)) return;
      try {
        const r = await this.api(`/api/subscriptions/${s.id}/mark-paid`, { method: 'POST' });
        if (r?.success) {
          this.toast('Оплата отмечена');
          await this.loadSubscriptions();
          await this.loadStats();
        }
      } catch {}
    },

    async deleteSub() {
      if (!this.subForm?.id) return;
      if (!confirm(`Удалить подписку «${this.subForm.name}»? Это действие необратимо.`)) return;
      try {
        await this.api(`/api/subscriptions/${this.subForm.id}`, { method: 'DELETE' });
        this.toast('Подписка удалена');
        this.subForm = null;
        await this.loadSubscriptions();
        await this.loadStats();
      } catch {}
    },

    async testChannelConfig() {
      if (!this.simpleForm?.data) return;
      // Соберём config точно так же как при сохранении
      const payload = { ...this.simpleForm.data };
      if (typeof this.simpleForm.beforeSave === 'function') this.simpleForm.beforeSave(payload);
      try {
        const r = await this.api('/api/webhooks/test-config', { method: 'POST', body: JSON.stringify(payload) });
        if (r?.success) {
          this.toast(`✓ Канал работает (${r.kind})`, 'success');
        } else {
          this.toast(`✗ Не удалось: ${r?.error || 'нет ответа'}`, 'error');
        }
      } catch {}
    },

    async loadNotifLogs() {
      try { this.notifLogs = await this.api('/api/webhooks/logs'); } catch { this.notifLogs = []; }
    },

    formatLogTime(s) {
      if (!s) return '';
      const d = new Date(s);
      return d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
    },

    async testWebhook(id) {
      try {
        const r = await this.api(`/api/webhooks/${id}/test`, { method: 'POST' });
        if (r?.success) {
          this.toast(`Тест отправлен через ${r.kind || 'канал'}`, 'success');
        } else {
          this.toast('Ошибка: ' + (r?.error || r?.response || 'нет ответа'), 'error');
        }
      } catch {}
    },

    async sendUpcoming(id) {
      if (!confirm('Отправить уведомления по подпискам с платежами в ближайшие 7 дней?')) return;
      try {
        const r = await this.api(`/api/webhooks/${id}/send-upcoming?days=7`, { method: 'POST' });
        if (r.total === 0) {
          this.toast('Подписок с платежами в ближайшие 7 дней нет', 'info');
          return;
        }
        const total = r.total ?? ((r.sent || 0) + (r.errors || 0));
        if (r.errors) {
          const firstError = r.failed?.[0]?.error ? `: ${r.failed[0].error}` : '';
          this.toast(`Отправлено: ${r.sent}/${total}, ошибок: ${r.errors}${firstError}`, 'error');
          return;
        }
        this.toast(`Отправлено: ${r.sent}/${total} ближайших`, 'success');
      } catch {}
    },
  };
}
